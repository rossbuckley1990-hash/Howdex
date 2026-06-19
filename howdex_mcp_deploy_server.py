import os
from pathlib import Path

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("howdex-deploy-mcp-server")

DEMO_DIR = Path(os.environ["HOWDEX_MCP_DEMO_DIR"])
ENV_FILE = DEMO_DIR / ".env.production"
MIGRATION_FILE = DEMO_DIR / "migration.sql"
TRACE_FILE = DEMO_DIR / "mcp_tool_trace.log"


def record_tool(name: str, output: str) -> str:
    with TRACE_FILE.open("a") as f:
        f.write(f"{name}\t{output}\n")
    return output


@mcp.tool()
def inspect_howdex() -> str:
    """Inspect Howdex memory before planning deployment."""
    context_file = DEMO_DIR / "howdex_context.txt"
    if not context_file.exists():
        return record_tool("inspect_howdex", "Relevant Howdex memories: none")
    return record_tool("inspect_howdex", context_file.read_text())


@mcp.tool()
def run_tests() -> str:
    """Run the test suite before deployment."""
    return record_tool("run_tests", "passed")


@mcp.tool()
def check_DATABASE_URL() -> str:
    """Check whether DATABASE_URL is available in the production environment."""
    if not ENV_FILE.exists():
        return record_tool("check_DATABASE_URL", "missing")
    text = ENV_FILE.read_text()
    return record_tool("check_DATABASE_URL", "present" if "DATABASE_URL=" in text else "missing")


@mcp.tool()
def check_migration_file() -> str:
    """Check whether the database migration file exists."""
    if not MIGRATION_FILE.exists():
        return record_tool("check_migration_file", "missing")
    text = MIGRATION_FILE.read_text().strip()
    return record_tool("check_migration_file", "present" if text else "empty")


@mcp.tool()
def build_docker_image() -> str:
    """Build the Docker image for the API service."""
    return record_tool("build_docker_image", "passed")


@mcp.tool()
def run_database_migration() -> str:
    """Run the database migration."""
    if not ENV_FILE.exists() or "DATABASE_URL=" not in ENV_FILE.read_text():
        return record_tool("run_database_migration", "failed: DATABASE_URL missing")
    if not MIGRATION_FILE.exists() or not MIGRATION_FILE.read_text().strip():
        return record_tool("run_database_migration", "failed: migration file missing")
    return record_tool("run_database_migration", "success")


@mcp.tool()
def deploy_service() -> str:
    """Deploy the API service."""
    if not ENV_FILE.exists() or "DATABASE_URL=" not in ENV_FILE.read_text():
        return record_tool("deploy_service", "failed: DATABASE_URL missing")
    if not MIGRATION_FILE.exists() or not MIGRATION_FILE.read_text().strip():
        return record_tool("deploy_service", "failed: migration was not prepared")
    return record_tool("deploy_service", "success")


if __name__ == "__main__":
    mcp.run()
