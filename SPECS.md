# AI Web Tester: Technical Specification

## Core Functionality

This tool uses Azure OpenAI's vision capabilities to automate web navigation. It:

1. Launches a browser with Playwright (headless by default, with option for visible mode)
2. Records video of the entire browsing session
3. Takes periodic screenshots to send to Azure OpenAI
4. Asks the AI "what should I click/type next?"
5. Executes the AI's decision
6. Continuously evaluates if the goal has been reached
7. Automatically terminates when the goal is completed

## Environment & Credentials Handling

* Uses `dotenv` to load environment variables from `.env`
* Requires `AZURE_OPENAI_ENDPOINT` and `AZURE_OPENAI_API_KEY` for API access
* Automatically detects common credential environment variables (`EMAIL`, `PASSWORD`, `USERNAME`, `API_KEY`, `PHONE`)
* Passes these variables to Azure OpenAI so it can decide when to use them for login forms
* Marks inputs as `secret=true` when using credentials to avoid logging

## Video Recording

* Continuously records the entire browser session
* Uses Playwright's built-in video recording:

```python
context = await browser.new_context(
    record_video_dir="./videos",
    record_video_size={"width": 1366, "height": 768}
)
```

* Creates separate video files for each tab/window if needed
* Video files are saved when the context closes
* Allows review of the complete session including:
   * Transitions between pages
   * Loading animations
   * Popup windows
   * Authentication flows

## Goal Detection

* Built-in feature that runs automatically (not an optional flag)
* After each action, evaluates if the current state matches the goal description
* Uses natural language understanding to determine goal completion status
* Sends current screenshot and goal description to Azure OpenAI
* Asks "Has the goal '[goal description]' been achieved in this screenshot?"
* Requires confident positive response for goal completion confirmation
* When goal is reached:
   * Takes final screenshot
   * Closes browser session
   * Finalizes video recording
   * Exits process with success code
   * Reports completion status

## System Prompt & AI Communication

* Uses a structured system prompt that tells the AI to:
   * Prioritize cookie banners and privacy prompts
   * Look for login forms and use environment variables
   * Handle Google sign-in flows
   * Deal with popups correctly
   * Evaluate goal completion after each step
* Sends three key pieces in each OpenAI request:
   1. Screenshot of current page (for AI vision)
   2. List of clickable elements with their properties
   3. Current navigation state (URL, step number)
* Forces JSON response format so the AI returns structured data
* Maintains a single continuous chat session throughout the entire test
* Preserves conversation history between steps (last 3-5 messages)
* Includes previous actions and their outcomes in the chat context
* Enables the AI to reference its prior decisions and reasoning
* Critical for goal completion detection as it allows the AI to:
   * Track progress toward the goal across multiple steps
   * Remember what it has already tried
   * Understand the current state in context of the journey
   * Make more informed decisions about goal completion

## Browser Session Management

* Uses Playwright's async API
* Headless mode by default, with command-line option for visible mode
* Handles multiple browser tabs/windows
* Registers event handlers for:
   * New pages/tabs opening
   * Dialog boxes (alerts, confirms)
   * Pages closing
* Maintains list of all open pages
* When a page closes, automatically switches to another open tab
* Verifies tab is valid before trying to use it

## Error Recovery Logic

* If a page closes unexpectedly (like after Google auth):
   * Finds another valid tab to continue with
   * If no tabs, creates a new one
* If AI fails to decide, picks first element as fallback
* If page load times out, falls back to less strict wait conditions
* If cookie banners are detected, automatically dismisses them

## Cookie Banner Handling

* Automatically scans for cookie consent banners when:
   * New page loads
   * After navigation
   * After switching tabs
* Uses list of common cookie banner selectors
* Two-phase detection:
   1. Look for cookie-related elements
   2. Try clicking acceptance buttons

## Performance Optimization

* Optimized for speed while maintaining reliability
* Smart waiting strategies:
   * Waits for network idle before processing
   * Uses DOM-ready state when possible
   * Progressive timeouts with sensible defaults
* Minimizes unnecessary delays
* Caches element information when appropriate
* Implements efficient selector strategies

## Command Line Interface

```
python web_tester.py --url "https://example.com" --goal "Sign in and check dashboard" --max-steps 20 --output-dir "./output" --video-quality "high" --headless false
```

Where:
* `url`: Starting website
* `goal`: Task description for the AI (also used for goal completion detection)
* `max-steps`: Maximum actions to take (default: 20)
* `output-dir`: Where to save screenshots and videos
* `video-quality`: Resolution of recorded videos (low/medium/high)
* `headless`: Whether to run in headless mode (default: true)

## Output & Artifacts

* Continuous video recording of the entire session
* Screenshots taken at decision points
* Terminal logs showing:
   * Elements found
   * AI decisions
   * Actions taken
   * Page changes
   * Goal completion status
* Final screenshot at goal completion
* Complete session report

## Goal Detection
* The system should be able to detect whether it has completed a 