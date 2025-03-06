# BugNinja - AI-Driven Web Testing Tool

BugNinja is an automated web testing tool that uses Azure OpenAI's vision capabilities to navigate websites and perform tasks without predefined scripts.

## Features

- 🤖 AI-driven navigation using Azure OpenAI's vision capabilities
- 🎥 Video recording of the entire browsing session
- 📸 Screenshot capture at each decision point
- 🍪 Smart cookie banner handling with AI vision
- 🔑 Secure credential handling for login forms
- 🎯 Automatic goal detection with AI vision analysis
- 🏆 Smart test completion when goal is achieved

## Installation

1. Clone this repository:
```bash
git clone https://github.com/yourusername/bugninja.git
cd bugninja
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Install Playwright browsers:
```bash
python -m playwright install
```

4. Create a `.env` file with your Azure OpenAI credentials:
```
AZURE_OPENAI_ENDPOINT=https://your-endpoint.openai.azure.com/
AZURE_OPENAI_API_KEY=your-api-key
AZURE_OPENAI_DEPLOYMENT_NAME=gpt-4o  # Or your deployment name
```

## Usage

Run BugNinja with the following command:

```bash
python bugninja.py --url "https://example.com" --goal "Sign in and check dashboard" --max-steps 20 --output-dir "./output" --headless
```

### Command Line Arguments

- `--url`: Starting website URL (required)
- `--goal`: Task description for the AI (required)
- `--max-steps`: Maximum actions to take (default: 10)
- `--output-dir`: Where to save screenshots and videos (default: ./output)
- `--headless`: Run in headless mode (flag, default is visible browser)
- `--video-quality`: Quality of video recording (low/medium/high, default: medium)
- `--goal-confidence`: Confidence threshold for goal detection (0.0-1.0, default: 0.8)

### Environment Variables

You can set these environment variables in your `.env` file for the AI to use when filling forms:

- `EMAIL`: Email address for login forms
- `PASSWORD`: Password for login forms
- `USERNAME`: Username for login forms
- `API_KEY`: API key for authentication
- `PHONE`: Phone number for forms

## How It Works

1. Launches a browser with Playwright
2. Ensures the page is fully loaded before proceeding
3. Takes screenshots of the current page
4. Sends the screenshot to Azure OpenAI
5. Checks if the goal has been achieved
6. If not, asks the AI "what should I click/type next?"
7. Executes the AI's decision
8. Repeats until the goal is reached or max steps are taken

## Improved Cookie Banner Handling

BugNinja uses AI vision to intelligently handle cookie banners and consent dialogs:

- The AI is instructed to give absolute top priority to cookie banners and consent dialogs
- No hardcoded selectors or patterns are used - the AI visually identifies consent elements
- The system ensures pages are fully loaded before taking screenshots and making decisions
- This approach works across different websites with varying cookie banner designs
- The AI can identify and handle cookie banners in multiple languages

## Automatic Goal Detection

BugNinja uses AI vision analysis to automatically detect when the testing goal has been achieved:

- After each step, the current screenshot and conversation history are analyzed by Azure OpenAI
- The AI evaluates whether the goal has been completed based on visual cues
- The AI considers previous actions and their outcomes when determining goal completion
- If the goal is detected as achieved with high confidence (>80%), the test completes successfully
- The AI provides an explanation of why it believes the goal was achieved
- This eliminates the need for predefined success criteria or manual verification
- You can adjust the confidence threshold with the `--goal-confidence` option

## Project Structure

```
bugninja_v1/
├── core/                 # Core functionality
│   ├── ai_service.py     # Azure OpenAI integration
│   ├── browser_manager.py # Browser session management
│   ├── element_finder.py # Web element detection
│   ├── action_executor.py # Action execution
│   ├── models.py         # Data models
│   └── web_tester.py     # Main WebTester class
├── handlers/             # Event handlers
│   ├── browser_handlers.py # Browser event handlers
│   └── cookie_handler.py # Cookie banner handling
├── utils/                # Utility functions
│   └── helpers.py        # Helper functions
├── __init__.py           # Package initialization
└── __main__.py           # Entry point
```

## License

MIT 