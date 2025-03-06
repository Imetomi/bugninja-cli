# Interactive Web Navigator

A command-line tool that allows you to navigate websites by interactively selecting elements based on their hierarchy levels.

## Features

- Automatically detects and ranks interactive elements on webpages
- Displays top elements sorted by importance/hierarchy level
- Takes screenshots of each page visited
- Allows interactive navigation through clicking elements
- Supports form input and link navigation
- Provides back, reload, and direct URL entry functionality

## Installation

### Prerequisites

- Python 3.7+
- pip

### Setup

1. Clone this repository:
   ```
   git clone https://github.com/yourusername/interactive-web-navigator.git
   cd interactive-web-navigator
   ```

2. Install required packages:
   ```
   pip install playwright pandas
   ```

3. Install Playwright browsers:
   ```
   python -m playwright install chromium
   ```

## Usage

Run the program with a starting URL:

```
python interactive_webbot.py https://example.com
```

### Command-line options:

- `--headless`, `-H`: Run in headless mode (no visible browser)
- `--output-dir`, `-o`: Directory to save screenshots (default: ./screenshots)
- `--count`, `-c`: Number of top elements to display (default: 10)

Example:
```
python interactive_webbot.py https://example.com --count 15 --output-dir ./my-screenshots
```

### Interactive Commands:

When the program is running, you can:

- Enter a number (0-9) to select and click an element
- Enter `b` to go back in the browser history
- Enter `r` to reload the current page
- Enter `u` to manually enter a new URL
- Enter `x` to exit the program

## How Element Ranking Works

Elements are ranked on a scale of 1-5, with 1 being the highest priority:

1. **Level 1**: Primary action elements (Sign up buttons, Submit, main calls-to-action)
2. **Level 2**: Important but secondary elements
3. **Level 3**: Standard interactive elements
4. **Level 4**: Less important interactive elements
5. **Level 5**: Low-priority or non-visible elements

The ranking algorithm considers:
- Element position in the DOM structure
- Text content and semantic importance
- Element type (buttons, links, inputs)
- Size and visibility on the page
- Whether an element is in an overlay/modal

## File Structure

- `interactive_webbot.py`: Main script and execution loop
- `web_analyzer.py`: Handles browser automation and element analysis
- `element_selector.py`: User interface for displaying and selecting elements

## Troubleshooting

### Common Issues:

1. **Navigation timeout errors**:
   - Try increasing the navigation timeout or using a different wait strategy
   - Some sites may have anti-bot measures

2. **Elements not clickable**:
   - The tool may need to be updated to handle complex dynamic sites
   - Try clicking a different element or navigating manually with 'u'

3. **Browser visibility issues**:
   - If using headless mode, try running without the `--headless` flag
   - Some sites detect and block headless browsers

## License

This project is licensed under the MIT License - see the LICENSE file for details.
