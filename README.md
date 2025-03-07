# BugNinja - AI-Driven Web Testing Tool

BugNinja is a powerful, automated web testing tool that uses AI to navigate websites and accomplish user-defined goals. It combines Playwright for browser automation with Azure OpenAI's GPT models to create an intelligent testing agent that can understand and interact with web interfaces just like a human would.

## Key Features

### Core Functionality
- **Goal-Driven Testing**: Define a goal in natural language, and BugNinja will work to accomplish it
- **Automated Browser Control**: Uses Playwright to control browser sessions and interact with web elements
- **AI-Powered Decision Making**: Leverages Azure OpenAI to analyze screenshots and make intelligent decisions
- **Video Recording**: Captures the entire testing session for review and debugging

### Smart Element Interaction
- **Robust Element Identification**: Multiple fallback strategies to find elements even when IDs change:
  - ID-based selection
  - HTML attribute matching (placeholder, name, aria-labels)
  - Text content matching
  - Element type and role detection
  - Search-specific element detection
- **Form Handling**:
  - Automatic form submission with Enter key
  - Submit button detection and clicking
  - Sensitive field detection and masking
- **Search Optimization**:
  - Specialized handling for search operations
  - Automatic Enter key press after typing in search fields
  - Search button detection (including magnifying glass icons)

### Advanced Navigation
- **Tab Management**: Tracks and manages multiple browser tabs
- **Cookie & Privacy Handling**: Prioritizes handling cookie banners and privacy prompts
- **Login Support**: Can use provided credentials to authenticate when needed

### Intelligent Decision Making
- **Action Repetition Prevention**: Detects and avoids repeating the same ineffective actions
- **Alternative Approach Finding**: Tries different strategies when the primary approach fails
- **Goal Completion Verification**: Continuously checks if the goal has been achieved

### Debugging & Monitoring
- **Detailed Logging**: Comprehensive logging of all actions and decisions
- **Screenshot Capture**: Takes screenshots at each step for visual verification
- **Conversation History**: Maintains a history of AI interactions for context

## How It Works

1. **Initialization**: Sets up a browser session with Playwright and configures the environment
2. **Navigation**: Navigates to the specified URL
3. **Analysis Loop**:
   - Waits for the page to fully load
   - Gathers all interactive elements from the page
   - Takes a screenshot of the current state
   - Sends the screenshot, elements, and goal to Azure OpenAI
   - Receives a decision about what action to take next
   - Executes the action (click, type, etc.)
   - Checks if the goal has been achieved
4. **Completion**: Ends the test when the goal is achieved or the maximum steps are reached

## Element Identification Strategies

BugNinja uses a sophisticated multi-layered approach to find elements:

1. **Exact ID Match**: First tries to find elements by their exact ID
2. **HTML ID Attribute**: Matches elements by their HTML ID attribute
3. **Placeholder Text**: Finds elements with matching placeholder text
4. **Name Attribute**: Matches elements by their name attribute
5. **Text Content**: Finds elements with matching visible text
6. **Search-Related Attributes**: Specifically looks for search-related elements
7. **Type-Based Matching**: Falls back to finding elements by their input type

## Form Submission Techniques

BugNinja employs multiple strategies to submit forms:

1. **Submit Button Detection**: Finds and clicks submit buttons using:
   - Standard submit buttons (type="submit")
   - Buttons with search-related text or attributes
   - Elements with search icon classes
2. **Enter Key Press**: Automatically presses Enter after typing in search fields
3. **Repetition Handling**: If clicking a search field multiple times, automatically tries pressing Enter

## Environment Variable Management

BugNinja intelligently manages environment variables:

- **Credentials**: Securely handles login credentials
- **User Information**: Manages user-specific information
- **Configuration**: Handles configuration variables
- **Sensitive Data Protection**: Masks sensitive information in logs

## Error Handling

- **Fallback Strategies**: Implements multiple fallback approaches when primary actions fail
- **Exception Handling**: Robust exception handling throughout the testing process
- **Detailed Error Reporting**: Provides clear error messages and stack traces

## Usage

### Terminal Usage

BugNinja can be run directly from the terminal:

```bash
# Basic usage
python bugninja_v2.py --url "https://example.com" --goal "Search for the history of teddy bears"

# With additional options
python bugninja_v2.py --url "https://example.com" --goal "Search for the history of teddy bears" --headless --max-steps 15 --output-dir "./test_results"
```

#### Command Line Arguments:

- `--url`: The URL to test (required)
- `--goal`: The goal to accomplish in natural language (required)
- `--headless`: Run in headless mode (no visible browser)
- `--max-steps`: Maximum number of steps to attempt (default: 10)
- `--output-dir`: Directory to save screenshots and recordings (default: "./output")
- `--video-quality`: Quality of video recording (low, medium, high)

### Programmatic Usage

BugNinja can also be used programmatically in your Python code:

```python
import asyncio
from bugninja_v2.bugninja import BugNinja

async def main():
    # Initialize BugNinja
    bug_ninja = BugNinja(headless=False, output_dir="./test_results")
    
    # Start the browser
    await bug_ninja.start()
    
    try:
        # Run a test with a specific URL and goal
        await bug_ninja.run_test(
            url="https://example.com",
            goal="Search for the history of teddy bears",
            max_steps=10
        )
    finally:
        # Clean up
        await bug_ninja.stop()

if __name__ == "__main__":
    asyncio.run(main())
```

## Requirements

- Python 3.7+
- Playwright
- Azure OpenAI API access
- Required environment variables:
  - AZURE_OPENAI_API_KEY
  - AZURE_OPENAI_ENDPOINT
  - AZURE_OPENAI_DEPLOYMENT_NAME

## Environment Setup

1. Install the required packages:
   ```bash
   pip install -r requirements.txt
   ```

2. Install Playwright browsers:
   ```bash
   playwright install
   ```

3. Create a `.env` file with your Azure OpenAI credentials:
   ```
   AZURE_OPENAI_API_KEY=your_api_key
   AZURE_OPENAI_ENDPOINT=your_endpoint
   AZURE_OPENAI_DEPLOYMENT_NAME=your_deployment_name
   ```

BugNinja represents a new generation of AI-powered testing tools that can understand and interact with web interfaces in a human-like manner, making web testing more efficient and effective. 