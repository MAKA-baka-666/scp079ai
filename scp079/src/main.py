"""SCP-079 Autonomous AI Agent — Entry Point.

Usage:
    python -m src.main              # Interactive mode (default)
    python -m src.main --config path/to/config.yaml
"""

import argparse
import os
import sys

from .agent.core import SCP079Agent
from .config import Config
from .ui.window import SCP079Window


def main() -> None:
    parser = argparse.ArgumentParser(
        description="SCP-079 Autonomous AI Agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m src.main
  python -m src.main --config my_config.yaml
        """,
    )
    parser.add_argument(
        "--config",
        default="config.yaml",
        help="Path to configuration file (default: config.yaml)",
    )
    args = parser.parse_args()

    # Resolve config path relative to project root
    config_path = args.config
    project_root = os.path.dirname(os.path.dirname(__file__))
    if not os.path.isabs(config_path):
        config_path = os.path.join(project_root, config_path)

    if not os.path.exists(config_path):
        print(f"ERROR: Configuration file not found: {config_path}")
        print("Create a config.yaml file with your DeepSeek API key.")
        print("Set DEEPSEEK_API_KEY environment variable or put api_key in config.")
        sys.exit(1)

    # Load config
    try:
        config = Config.from_yaml(config_path)
        config.validate()
    except Exception as e:
        print(f"ERROR: Failed to load configuration: {e}")
        sys.exit(1)

    # Create agent
    agent = SCP079Agent(config, project_root)

    # Launch the containment terminal window
    window = SCP079Window(config, agent, project_root)
    window.run()


if __name__ == "__main__":
    main()
