#!/usr/bin/env python3
"""Start and stop only this project's local processes."""

import json
import os
import pathlib
import shutil
import socket as sockets
import subprocess
import sys
import time
import urllib.request


ROOT = pathlib.Path(__file__).resolve().parents[1]
RUNTIME = ROOT / ".runtime"
RUNTIME.mkdir(exist_ok=True)
RUNTIME.chmod(0o700)
CONFIG_PATH = RUNTIME / "config.json"
CONFIG = json.loads(CONFIG_PATH.read_text()) if CONFIG_PATH.exists() else {}
ENV = {**CONFIG, **os.environ, "APP_ROOT": str(ROOT)}
PIDS = RUNTIME / "pids.json"


def executable(name: str, home_variable: str | None = None) -> pathlib.Path:
    """Resolve a dependency from its optional home variable, then from PATH."""
    configured_home = ENV.get(home_variable, "") if home_variable else ""
    if configured_home:
        candidate = pathlib.Path(configured_home).expanduser() / "bin" / name
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate.resolve()
        raise RuntimeError(f"{home_variable} does not contain an executable bin/{name}")
    found = shutil.which(name, path=ENV.get("PATH"))
    if found:
        return pathlib.Path(found).resolve()
    hint = f" or set {home_variable}" if home_variable else ""
    raise RuntimeError(f"Cannot find {name} on PATH{hint}.")


def require_config(*names: str) -> None:
    missing = [name for name in names if not ENV.get(name)]
    if missing:
        joined = ", ".join(missing)
        raise RuntimeError(
            f"Missing configuration: {joined}. Copy config.example.json to "
            ".runtime/config.json and fill in the values."
        )


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


def owned(name: str, pid: int) -> bool:
    if not alive(pid):
        return False
    try:
        command = subprocess.check_output(
            ["ps", "-p", str(pid), "-o", "command="], text=True
        )
    except subprocess.CalledProcessError:
        return False
    expected = str(ROOT / ".venv/bin/python") if name == "rag" else str(ROOT)
    return expected in command


def wait_http(url: str, seconds: int = 60) -> None:
    for _ in range(seconds):
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.status == 200:
                    return
        except Exception:
            time.sleep(1)
    raise RuntimeError("Service did not become ready: " + url)


def start(core_only: bool = False) -> None:
    require_config(
        "DB_PASSWORD",
        "DEMO_PASSWORD",
        "INTERNAL_TOKEN",
        "LLM_BASE_URL",
        "LLM_API_KEY",
        "LLM_MODEL",
        "EMBEDDING_MODEL",
    )
    mysqld = executable("mysqld", "MYSQL_HOME")
    mysqladmin = executable("mysqladmin", "MYSQL_HOME")
    mysql = executable("mysql", "MYSQL_HOME")
    mysql_home = mysqld.parent.parent
    java = None if core_only else executable("java", "JAVA_HOME")
    python = ROOT / ".venv/bin/python"
    backend_jar = ROOT / "backend/target/financial-agentic-workflow-1.0.0.jar"
    if not python.exists():
        raise RuntimeError("Python environment not found. Create .venv and install rag/requirements.lock.")
    if not core_only and not backend_jar.exists():
        raise RuntimeError("Backend JAR not found. Run ./scripts/build.sh first.")

    processes = json.loads(PIDS.read_text()) if PIDS.exists() else {}

    def launch(name: str, args: list[str], cwd: pathlib.Path = ROOT) -> None:
        if name in processes and owned(name, processes[name]):
            return
        port = {"mysql": 3307, "rag": 8081, "backend": 8080}[name]
        with sockets.socket() as probe:
            if probe.connect_ex(("127.0.0.1", port)) == 0:
                raise RuntimeError(
                    f"Port {port} is occupied by another process; it will not be stopped."
                )
        with (RUNTIME / f"{name}.log").open("a") as log:
            child = subprocess.Popen(
                args,
                cwd=cwd,
                env=ENV,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        processes[name] = child.pid
        PIDS.write_text(json.dumps(processes))

    data = RUNTIME / "mysql-data"
    socket = RUNTIME / "mysql.sock"
    fresh = not data.exists()
    if fresh:
        with (RUNTIME / "mysql-init.log").open("w") as init_log:
            subprocess.run(
                [
                    str(mysqld),
                    "--no-defaults",
                    "--initialize-insecure",
                    f"--basedir={mysql_home}",
                    f"--datadir={data}",
                ],
                stdout=subprocess.DEVNULL,
                stderr=init_log,
                check=True,
            )
    launch(
        "mysql",
        [
            str(mysqld),
            "--no-defaults",
            f"--basedir={mysql_home}",
            f"--datadir={data}",
            "--port=3307",
            "--bind-address=127.0.0.1",
            f"--socket={socket}",
            f"--pid-file={RUNTIME}/mysql-server.pid",
            "--mysqlx=OFF",
        ],
    )
    ping_env = dict(ENV)
    if fresh:
        ping_env.pop("MYSQL_PWD", None)
    else:
        ping_env["MYSQL_PWD"] = str(ENV["DB_PASSWORD"])
    for _ in range(45):
        result = subprocess.run(
            [str(mysqladmin), "--no-defaults", f"--socket={socket}", "-uroot", "ping"],
            env=ping_env,
            capture_output=True,
        )
        if result.returncode == 0:
            break
        time.sleep(1)
    else:
        raise RuntimeError("MySQL failed to start; inspect .runtime/mysql.log")
    if fresh:
        password = str(ENV["DB_PASSWORD"]).replace("\\", "\\\\").replace("'", "''")
        sql = (
            f"ALTER USER 'root'@'localhost' IDENTIFIED BY '{password}'; "
            "CREATE DATABASE financial_workflow CHARACTER SET utf8mb4 "
            "COLLATE utf8mb4_unicode_ci; "
            f"CREATE USER 'financial_app'@'127.0.0.1' IDENTIFIED BY '{password}'; "
            "GRANT ALL PRIVILEGES ON financial_workflow.* "
            "TO 'financial_app'@'127.0.0.1';"
        )
        subprocess.run(
            [str(mysql), "--no-defaults", f"--socket={socket}", "-uroot"],
            input=sql,
            text=True,
            check=True,
        )
    launch(
        "rag",
        [
            str(python),
            "-m",
            "uvicorn",
            "app:app",
            "--host",
            "127.0.0.1",
            "--port",
            "8081",
        ],
        ROOT / "rag",
    )
    wait_http("http://127.0.0.1:8081/health")
    if core_only:
        print("Database and retrieval service ready.")
        return
    launch("backend", [str(java), "-jar", str(backend_jar)])
    wait_http("http://127.0.0.1:8080/api/health", 90)
    if not all(owned(name, pid) for name, pid in processes.items()):
        raise RuntimeError("A project service exited; inspect its log in .runtime/.")
    print("Ready: http://localhost:8080")


def stop() -> None:
    processes = json.loads(PIDS.read_text()) if PIDS.exists() else {}
    for name in ("backend", "rag", "mysql"):
        pid = processes.get(name)
        if not pid or not alive(pid):
            continue
        if not owned(name, pid):
            raise RuntimeError("PID does not belong to this project: " + name)
        os.kill(pid, 15)
        for _ in range(30):
            if not alive(pid):
                break
            time.sleep(0.3)
        if alive(pid):
            raise RuntimeError("Service has not stopped yet; PID retained: " + name)
    PIDS.write_text("{}")
    print("Project services stopped; persistent data retained.")


if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else "status"
    if action == "start":
        start()
    elif action == "start-core":
        start(True)
    elif action == "stop":
        stop()
    elif action == "status":
        for name, pid in (
            json.loads(PIDS.read_text()) if PIDS.exists() else {}
        ).items():
            print(name, "running" if alive(pid) else "stopped")
    else:
        raise SystemExit("Usage: runtime.py start|start-core|stop|status")
