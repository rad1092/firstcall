//! One `serve` process for several exported tools.
use std::fs;
use std::io::{Read, Write};
use std::net::TcpListener;
use std::path::Path;
use std::process::{Command, Output, Stdio};
use std::thread;
use std::time::{Duration, Instant};

use firstcall::export::agent_package::export_agent_package;
use firstcall::model::{AuthStyle, BodyTemplate, Confidence, Recipe, RuntimeSlot, SlotLocation};
use serde_json::{Value, json};
use tempfile::TempDir;

fn slot(name: &str, location: SlotLocation) -> RuntimeSlot {
    RuntimeSlot {
        name: name.into(),
        location,
        required: true,
        current_value: None,
        description: format!("The {name} to look up"),
        confidence: Confidence::High,
    }
}

fn bearer_recipe(url: String) -> Recipe {
    Recipe {
        id: None,
        name: "Lookup".into(),
        method: "GET".into(),
        url_template: url,
        headers_template: vec![],
        query_template: vec![],
        body_template: BodyTemplate::None,
        auth_style: AuthStyle::Bearer {
            token_slot: "bearer_token".into(),
            header_name: "Authorization".into(),
        },
        slots: vec![
            slot("id", SlotLocation::Path),
            slot("bearer_token", SlotLocation::Auth),
        ],
        last_success_at: Some(chrono::Utc::now()),
        last_success_status: Some(200),
    }
}

fn export(recipe: &Recipe, dir: &Path, name: &str) {
    export_agent_package(recipe, dir).unwrap();
    fs::write(
        dir.join("tool.json"),
        json!({"schema_version":1,"name":name,"title":name,
            "description":"Look up one record by its id and return it as JSON.",
            "input_schema":{"type":"object","properties":{"id":{"type":"string","description":"Record id"}},
                "required":["id"],"additionalProperties":false}})
        .to_string(),
    )
    .unwrap();
}

fn listener() -> (TcpListener, String) {
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let origin = format!("http://{}", listener.local_addr().unwrap());
    listener.set_nonblocking(true).unwrap();
    (listener, origin)
}

/// Answers one request with `{"from": label}` and returns the request head.
fn answer_once(listener: TcpListener, label: &'static str) -> thread::JoinHandle<Option<String>> {
    thread::spawn(move || {
        let deadline = Instant::now() + Duration::from_secs(10);
        let mut stream = loop {
            match listener.accept() {
                Ok((stream, _)) => break stream,
                Err(_) if Instant::now() < deadline => thread::sleep(Duration::from_millis(10)),
                Err(_) => return None,
            }
        };
        stream.set_nonblocking(false).unwrap();
        let mut request = Vec::new();
        let mut byte = [0; 1];
        while !request.ends_with(b"\r\n\r\n") {
            stream.read_exact(&mut byte).unwrap();
            request.push(byte[0]);
        }
        let body = json!({ "from": label }).to_string();
        let response = format!(
            "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",
            body.len()
        );
        stream.write_all(response.as_bytes()).unwrap();
        Some(String::from_utf8(request).unwrap())
    })
}

fn handshake() -> Vec<Value> {
    vec![
        json!({"jsonrpc":"2.0","id":1,"method":"initialize","params":{
            "protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"test","version":"1"}}}),
        json!({"jsonrpc":"2.0","method":"notifications/initialized"}),
    ]
}

fn call(id: u64, name: &str) -> Value {
    json!({"jsonrpc":"2.0","id":id,"method":"tools/call","params":{"name":name,"arguments":{"id":"7"}}})
}

fn serve(args: &[&str], messages: &[Value], env: &[(&str, &str)]) -> (Output, Vec<Value>) {
    let mut command = Command::new(env!("CARGO_BIN_EXE_firstcall-cli"));
    command
        .env_clear()
        .arg("serve")
        .args(args)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    for (key, value) in env {
        command.env(key, value);
    }
    let mut child = command.spawn().unwrap();
    let input: String = messages
        .iter()
        .map(|message| format!("{message}\n"))
        .collect();
    let _ = child.stdin.take().unwrap().write_all(input.as_bytes());
    let output = child.wait_with_output().unwrap();
    let responses = String::from_utf8_lossy(&output.stdout)
        .lines()
        .map(|line| serde_json::from_str(line).unwrap())
        .collect();
    (output, responses)
}

#[test]
fn one_server_lists_and_calls_tools_for_two_apis_with_their_own_tokens() {
    let root = TempDir::new().unwrap();
    let (users_listener, users_origin) = listener();
    let (repos_listener, repos_origin) = listener();
    export(
        &bearer_recipe(format!("{users_origin}/users/{{{{id}}}}")),
        &root.path().join("users"),
        "find_user",
    );
    export(
        &bearer_recipe(format!("{repos_origin}/repos/{{{{id}}}}")),
        &root.path().join("repos"),
        "find_repo",
    );
    let users = answer_once(users_listener, "users");
    let repos = answer_once(repos_listener, "repos");

    let mut messages = handshake();
    messages.push(json!({"jsonrpc":"2.0","id":2,"method":"tools/list"}));
    messages.push(call(3, "find_user"));
    messages.push(call(4, "find_repo"));
    let toolbox = root.path().to_str().unwrap();
    let (output, responses) = serve(
        &["--toolbox", toolbox],
        &messages,
        &[
            ("FIRSTCALL_BEARER_TOKEN__FIND_USER", "users-token"),
            ("FIRSTCALL_BEARER_TOKEN__FIND_REPO", "repos-token"),
        ],
    );
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );

    let names: Vec<_> = responses[1]["result"]["tools"]
        .as_array()
        .unwrap()
        .iter()
        .map(|tool| tool["name"].as_str().unwrap().to_string())
        .collect();
    assert_eq!(names, ["find_repo", "find_user"]);
    assert_eq!(
        responses[2]["result"]["structuredContent"]["data"]["from"],
        "users"
    );
    assert_eq!(
        responses[3]["result"]["structuredContent"]["data"]["from"],
        "repos"
    );

    let users_request = users.join().unwrap().unwrap().to_ascii_lowercase();
    let repos_request = repos.join().unwrap().unwrap().to_ascii_lowercase();
    assert!(
        users_request.contains("authorization: bearer users-token"),
        "{users_request}"
    );
    assert!(
        repos_request.contains("authorization: bearer repos-token"),
        "{repos_request}"
    );
}

#[test]
fn a_shared_token_is_not_sent_when_two_apis_need_one() {
    let root = TempDir::new().unwrap();
    let (users_listener, users_origin) = listener();
    let (repos_listener, repos_origin) = listener();
    let users_dir = root.path().join("users");
    let repos_dir = root.path().join("repos");
    export(
        &bearer_recipe(format!("{users_origin}/users/{{{{id}}}}")),
        &users_dir,
        "find_user",
    );
    export(
        &bearer_recipe(format!("{repos_origin}/repos/{{{{id}}}}")),
        &repos_dir,
        "find_repo",
    );

    let mut messages = handshake();
    messages.push(call(2, "find_user"));
    let (output, responses) = serve(
        &[
            "--package",
            users_dir.to_str().unwrap(),
            "--package",
            repos_dir.to_str().unwrap(),
        ],
        &messages,
        &[("FIRSTCALL_BEARER_TOKEN", "which-api-is-this-for")],
    );
    assert!(output.status.success());
    assert_eq!(responses[1]["result"]["isError"], true);
    for listener in [users_listener, repos_listener] {
        assert!(
            listener.accept().is_err(),
            "no request should have been sent"
        );
    }
}

#[test]
fn a_single_package_still_reads_the_plain_variable() {
    let root = TempDir::new().unwrap();
    let (users_listener, users_origin) = listener();
    let users_dir = root.path().join("users");
    export(
        &bearer_recipe(format!("{users_origin}/users/{{{{id}}}}")),
        &users_dir,
        "find_user",
    );
    let users = answer_once(users_listener, "users");

    let mut messages = handshake();
    messages.push(call(2, "find_user"));
    let (output, responses) = serve(
        &["--package", users_dir.to_str().unwrap()],
        &messages,
        &[("FIRSTCALL_BEARER_TOKEN", "plain-token")],
    );
    assert!(output.status.success());
    assert_eq!(
        responses[1]["result"]["structuredContent"]["data"]["from"],
        "users"
    );
    assert!(
        users
            .join()
            .unwrap()
            .unwrap()
            .to_ascii_lowercase()
            .contains("bearer plain-token")
    );
}

#[test]
fn duplicate_tool_names_are_rejected_before_the_handshake() {
    let root = TempDir::new().unwrap();
    let (_, origin) = listener();
    let first = root.path().join("first");
    let second = root.path().join("second");
    export(
        &bearer_recipe(format!("{origin}/a/{{{{id}}}}")),
        &first,
        "lookup",
    );
    export(
        &bearer_recipe(format!("{origin}/b/{{{{id}}}}")),
        &second,
        "lookup",
    );
    let (output, responses) = serve(
        &[
            "--package",
            first.to_str().unwrap(),
            "--package",
            second.to_str().unwrap(),
        ],
        &handshake(),
        &[],
    );
    assert!(!output.status.success());
    assert!(responses.is_empty());
    assert!(
        String::from_utf8_lossy(&output.stderr).contains("Two packages use the tool name `lookup`")
    );
}

#[test]
fn connect_writes_one_server_entry_with_a_variable_per_api() {
    let root = TempDir::new().unwrap();
    let (_, users_origin) = listener();
    let (_, repos_origin) = listener();
    export(
        &bearer_recipe(format!("{users_origin}/users/{{{{id}}}}")),
        &root.path().join("users"),
        "find_user",
    );
    export(
        &bearer_recipe(format!("{repos_origin}/repos/{{{{id}}}}")),
        &root.path().join("repos"),
        "find_repo",
    );
    let output = Command::new(env!("CARGO_BIN_EXE_firstcall-cli"))
        .args(["connect", "--toolbox"])
        .arg(root.path())
        .output()
        .unwrap();
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let config: Value = serde_json::from_slice(&output.stdout).unwrap();
    let server = &config["mcpServers"]["firstcall"];
    let args: Vec<_> = server["args"]
        .as_array()
        .unwrap()
        .iter()
        .map(|a| a.as_str().unwrap())
        .collect();
    assert_eq!(args.iter().filter(|arg| **arg == "--package").count(), 2);
    let env = server["env"].as_object().unwrap();
    assert!(env.contains_key("FIRSTCALL_BEARER_TOKEN__FIND_USER"));
    assert!(env.contains_key("FIRSTCALL_BEARER_TOKEN__FIND_REPO"));
    assert!(!env.contains_key("FIRSTCALL_BEARER_TOKEN"));
}
