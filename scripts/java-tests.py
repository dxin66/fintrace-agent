#!/usr/bin/env python3
"""Run the Java integration tests against the project's local MySQL instance."""

import json
import os
import pathlib
import shutil
import subprocess


ROOT = pathlib.Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / ".runtime/config.json"
CONFIG = json.loads(CONFIG_PATH.read_text()) if CONFIG_PATH.exists() else {}
ENV = {**CONFIG, **os.environ}


def executable(name: str, home_variable: str) -> str:
    configured_home = ENV.get(home_variable, "")
    if configured_home:
        candidate = pathlib.Path(configured_home).expanduser() / "bin" / name
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate.resolve())
        raise RuntimeError(f"{home_variable} does not contain an executable bin/{name}")
    found = shutil.which(name, path=ENV.get("PATH"))
    if found:
        return found
    raise RuntimeError(f"Cannot find {name} on PATH or through {home_variable}.")


if not ENV.get("DB_PASSWORD"):
    raise RuntimeError(
        "DB_PASSWORD is missing. Copy config.example.json to .runtime/config.json first."
    )

mysql = executable("mysql", "MYSQL_HOME")
maven = executable("mvn", "MAVEN_HOME")
test_env = {
    **ENV,
    "MYSQL_PWD": str(ENV["DB_PASSWORD"]),
    "SPRING_DATASOURCE_URL": (
        "jdbc:mysql://127.0.0.1:3307/financial_workflow_test"
        "?serverTimezone=Asia/Shanghai"
    ),
}
subprocess.run(
    [
        mysql,
        "--no-defaults",
        "--socket=" + str(ROOT / ".runtime/mysql.sock"),
        "-uroot",
    ],
    env=test_env,
    input=(
        "CREATE DATABASE IF NOT EXISTS financial_workflow_test "
        "CHARACTER SET utf8mb4; "
        "GRANT ALL PRIVILEGES ON financial_workflow_test.* "
        "TO 'financial_app'@'127.0.0.1';"
    ),
    text=True,
    check=True,
)
maven_args = [maven, "-s", str(ROOT / "scripts/maven-settings.xml"), "test"]
if ENV.get("MAVEN_REPO_LOCAL"):
    maven_args.insert(1, f"-Dmaven.repo.local={ENV['MAVEN_REPO_LOCAL']}")
result = subprocess.run(maven_args, cwd=ROOT / "backend", env=test_env)
raise SystemExit(result.returncode)
