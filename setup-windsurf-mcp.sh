#!/bin/bash
# Setup script to configure Windsurf MCP for the movie catalog project

echo "Setting up Windsurf MCP configuration..."

# Create the Windsurf config directory if it doesn't exist
mkdir -p ~/.codeium/windsurf

# Get the project directory
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Create the MCP config file
cat > ~/.codeium/windsurf/mcp_config.json << EOF
{
  "mcpServers": {
    "movie-catalog": {
      "command": "${PROJECT_DIR}/.venv/bin/python3",
      "args": [
        "${PROJECT_DIR}/src/mcp_server.py"
      ],
      "env": {
        "PYTHONPATH": "${PROJECT_DIR}/src"
      },
      "cwd": "${PROJECT_DIR}"
    }
  }
}
EOF

echo "✓ MCP configuration saved to ~/.codeium/windsurf/mcp_config.json"
echo ""
echo "Available MCP tools:"
echo "  - analyze_and_match_movie: Analyze a movie title and find OMDB match"
echo "  - batch_analyze_titles: Process multiple titles at once"
echo "  - get_failed_matches_report: Get report of failed OMDB enrichments"
echo "  - detect_title_patterns: Analyze titles for OCR artifacts"
echo "  - confirm_match: Confirm a correct match and update Source of Truth"
echo ""
echo "To use:"
echo "1. Restart Windsurf if it's already running"
echo "2. Open Cascade panel"
echo "3. Look for the MCP icon in the top right"
echo "4. The 'movie-catalog' MCP should appear in the list"
