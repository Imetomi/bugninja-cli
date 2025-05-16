# BugNinja v3 Specifications

## Overview

BugNinja v3 is a modular, AI-driven web testing tool that uses computer vision and natural language processing to automate web interactions. It's designed to simulate human-like behavior while navigating websites and performing tasks.

## Architecture

BugNinja v3 is built with a modular architecture consisting of three main components / classes:

1. **WebCrawler**: Handles browser automation, element detection, and web interactions
2. **AIController**: Manages AI decision-making and image analysis
3. **BugNinja**: Orchestrates the testing process and coordinates between components

## Key Features

- **Coordinate-based interactions**: Uses pixel coordinates for precise clicking and typing
- **Human-like behavior**: Natural mouse movements and typing patterns
- **Multi-tab/window support**: Handles new tabs and windows automatically
- **Robust error handling**: Gracefully handles errors at multiple levels
- **Managing input with generated terms and and made-up **
- **Delayed goal verification**: Ensures final state is captured after actions

## Component Specifications

### WebCrawler

The WebCrawler component is responsible for all browser-related operations:

- Browser initialization with anti-detection measures
- Page navigation and loading
- Element detection and interaction
- Screenshot capture
- Tab and window management

#### Element Detection

Elements are detected using JavaScript evaluation that:
1. Finds all interactive elements (buttons, links, inputs, etc.)
2. Calculates their position, size, and center points
3. Extracts relevant attributes (text, placeholder, aria-label, etc.)

```javascript
// Element detection JavaScript
function isVisible(el) {
    try {
        const rect = el.getBoundingClientRect();
        const style = window.getComputedStyle(el);
        return rect.width > 0 && rect.height > 0 && 
               style.display !== 'none' && 
               style.visibility !== 'hidden' && 
               parseFloat(style.opacity) > 0;
    } catch (e) {
        return false;
    }
}

// Find all interactive elements
const elements = [];
const selectors = 'a, button, input, select, textarea, [role="button"], [role="link"], [role="checkbox"], [onclick]';

document.querySelectorAll(selectors).forEach(el => {
    if (!isVisible(el)) return;
    
    const rect = el.getBoundingClientRect();
    elements.push({
        tag: el.tagName.toLowerCase(),
        type: el.type || '',
        x: rect.left,
        y: rect.top,
        width: rect.width,
        height: rect.height,
        text: (el.textContent || '').trim(),
        placeholder: el.placeholder || '',
        value: el.value || '',
        aria_label: el.getAttribute('aria-label') || '',
        id: el.id || '',
        class_name: el.className || '',
        center_x: rect.left + rect.width / 2,
        center_y: rect.top + rect.height / 2
    });
});
```

#### Natural Mouse Movement

Mouse movements follow a natural curve using quadratic Bezier curves:

```python
async def _move_mouse_naturally(self, target_x: float, target_y: float):
    """Move mouse in a natural curve to target coordinates"""
    current = await self.page.evaluate("() => ({ x: window.mouseX || 0, y: window.mouseY || 0 })")
    start_x, start_y = current.get("x", 0), current.get("y", 0)
    
    # Create control point for quadratic bezier curve
    control_x = start_x + (target_x - start_x) * random.uniform(0.3, 0.7)
    control_y = start_y + (target_y - start_y) * random.uniform(0.3, 0.7)
    control_x += random.uniform(-50, 50)
    control_y += random.uniform(-50, 50)
    
    steps = 10
    for i in range(steps + 1):
        t = i / steps
        x = int((1-t)**2 * start_x + 2*(1-t)*t * control_x + t**2 * target_x)
        y = int((1-t)**2 * start_y + 2*(1-t)*t * control_y + t**2 * target_y)
        await self.page.mouse.move(x, y)
        await asyncio.sleep(random.uniform(0.01, 0.03))
```

#### Tab and Window Management

The WebCrawler tracks all open tabs/windows and handles switching between them:

- When a new tab/window opens, it's automatically detected and made active
- When a tab/window closes, the system reverts to the previous one
- All tabs/windows are properly cleaned up when the test ends

#### Tab and Window Management

The WebCrawler tracks all open tabs/windows and handles switching between them:

- When a new tab/window opens, it's automatically detected and made active
- When a tab/window closes, the system reverts to the previous one
- All tabs/windows are properly cleaned up when the test ends


### AI Controller

The AIController component handles all AI-related tasks:

- Communication with Azure OpenAI
- Decision-making based on screenshots and element data
- Conversation history management
- Goal achievement detection
- The code below shows how to define Azure's client. Import this class from the python OpenAI library. 

```python
self.client = AsyncAzureOpenAI(
   api_key=os.getenv("AZURE_OPENAI_API_KEY"),
   api_version="2023-12-01-preview",
   azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
)
```

#### System Prompt

The system prompt guides the AI's decision-making process:

```
You are an AI web tester. Analyze the page and decide the next action.
Respond in JSON format with:
{
    "action": "click" or "type",
    "coordinates": {"x": float, "y": float},
    "input_text": "text to type" (for type action),
    "reasoning": "explanation",
    "goal_achieved": boolean,
    "confidence": 0.0-1.0
}
Use the exact coordinates provided in the elements list for precise interactions.

IMPORTANT GUIDELINES:
1. ALWAYS handle cookie consent banners first before proceeding with the main task
2. For login forms, use credentials provided in the environment variables
3. When searching, first identify the search box, then type the query
4. For navigation, prefer clicking on main menu items rather than using browser controls
5. If you see a new tab or window open, continue working in that tab until it's closed
6. Report goal achievement only when you're confident the task is complete

When analyzing elements:
- Look for clear text indicators of button/link purpose
- Check aria-labels and placeholders for accessibility information
- Consider the position of elements on the page
- Prioritize visible, interactive elements
```

### BugNinja

The BugNinja component orchestrates the testing process:

- Initializes the WebCrawler and AIController
- Manages the main testing loop
- Handles goal achievement detection
- Ensures proper cleanup of resources

#### Delayed Goal Verification

To ensure the final state is captured, goal verification is delayed until after the action is performed:

```python
# Store goal achievement status for next iteration
pending_goal_achieved = decision.get("goal_achieved", False)
pending_confidence = decision.get("confidence", 0)

# Execute decision
# ...

# Check if we had a pending goal achievement from previous step
if pending_goal_achieved and pending_confidence >= 0.8:
    self.goal_achieved = True
    print(f"🎉 Goal achieved with confidence {pending_confidence:.2f}")
    print("📸 Final state captured in screenshot")
    break
```

## Usage Examples

### Basic Usage

```python
async def main():
    bugninja = BugNinja(headless=False)
    await bugninja.run_test(
        url="https://www.google.com",
        goal="Search for 'OpenAI' and click the first result"
    )

asyncio.run(main())
```

## Error Handling

BugNinja v3 implements robust error handling at multiple levels:

1. **JavaScript-level**: Try-catch blocks around element processing
2. **Python-level**: Exception handling around API calls and browser interactions
3. **Recovery mechanisms**: Automatic handling of page crashes and navigation errors