import os
import argparse
import json
from dataclasses import dataclass, asdict
from typing import List, Dict, Any, Optional

import asyncio
from playwright.async_api import async_playwright, Page, ElementHandle
import pandas as pd


@dataclass
class ActionableElement:
    """Class for storing information about actionable elements on a webpage."""

    element_type: str  # 'button', 'link', 'input', etc.
    text: str  # The text content of the element
    selector: str  # CSS or XPath selector to uniquely identify this element
    location: Dict[str, float]  # x, y coordinates and dimensions
    attributes: Dict[str, str]  # All HTML attributes of the element
    is_visible: bool  # Whether the element is visible on the page


class WebScraper:
    """A web scraper using Playwright that captures screenshots and identifies actionable elements."""

    def __init__(self, headless: bool = True, trace: bool = False):
        """Initialize the WebScraper with Playwright settings.

        Args:
            headless (bool): Whether to run the browser in headless mode
            trace (bool): Whether to record a trace for debugging
        """
        self.headless = headless
        self.trace = trace
        self.browser = None
        self.context = None
        self.page = None

    async def __aenter__(self):
        """Setup method for async context manager."""
        self.playwright = await async_playwright().start()

        # Configure browser for truly headless operation
        browser_options = {
            "headless": self.headless,
            # Additional options for better headless performance
            "args": [
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-accelerated-2d-canvas",
                "--no-first-run",
                "--no-zygote",
                "--disable-gpu",
            ],
        }

        self.browser = await self.playwright.chromium.launch(**browser_options)

        context_options = {
            "viewport": {"width": 1920, "height": 1080},
            # Ignore HTTPS errors for better reliability in headless mode
            "ignore_https_errors": True,
            # User agent to avoid bot detection
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        }

        self.context = await self.browser.new_context(**context_options)

        if self.trace:
            await self.context.tracing.start(screenshots=True, snapshots=True)

        self.page = await self.context.new_page()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Cleanup method for async context manager."""
        if self.trace:
            await self.context.tracing.stop(path="trace.zip")
        await self.context.close()
        await self.browser.close()
        await self.playwright.stop()

    async def navigate(self, url: str) -> bool:
        """Navigate to the specified URL.

        Args:
            url (str): The URL to navigate to

        Returns:
            bool: True if navigation was successful, False otherwise
        """
        try:
            # Set default timeout to handle slow-loading pages
            self.page.set_default_timeout(30000)  # 30 seconds

            # Set custom headers to avoid bot detection
            await self.page.set_extra_http_headers(
                {
                    "Accept-Language": "en-US,en;q=0.9",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                }
            )

            # Navigate to the URL with proper wait states
            response = await self.page.goto(
                url, wait_until="networkidle", timeout=60000  # 60 seconds max
            )

            # Wait for any possible client-side rendering to complete
            await self.page.wait_for_load_state("domcontentloaded")
            await asyncio.sleep(2)  # Additional wait for client-side JS

            return response.ok
        except Exception as e:
            print(f"Error navigating to {url}: {e}")
            return False

    async def take_screenshot(self, output_path: str) -> Optional[str]:
        """Take a screenshot of the current page.

        Args:
            output_path (str): Path where the screenshot should be saved

        Returns:
            Optional[str]: Path to the saved screenshot, or None if failed
        """
        try:
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            await self.page.screenshot(path=output_path, full_page=True)
            print(f"Screenshot saved to {output_path}")
            return output_path
        except Exception as e:
            print(f"Error taking screenshot: {e}")
            return None

    async def find_actionable_elements(self) -> List[ActionableElement]:
        """Find all actionable elements on the current page.

        Returns:
            List[ActionableElement]: List of ActionableElement objects
        """
        actionable_elements = []

        # Find buttons
        buttons = await self.page.query_selector_all(
            "button, input[type='button'], input[type='submit']"
        )
        for button in buttons:
            element = await self._create_actionable_element(button, "button")
            if element:
                actionable_elements.append(element)

        # Find links
        links = await self.page.query_selector_all("a")
        for link in links:
            element = await self._create_actionable_element(link, "link")
            if element:
                actionable_elements.append(element)

        # Find form inputs (excluding buttons already captured)
        inputs = await self.page.query_selector_all(
            "input:not([type='button']):not([type='submit'])"
        )
        for input_elem in inputs:
            input_type = await input_elem.get_attribute("type") or "text"
            element = await self._create_actionable_element(
                input_elem, f"input-{input_type}"
            )
            if element:
                actionable_elements.append(element)

        # Find select dropdowns
        selects = await self.page.query_selector_all("select")
        for select in selects:
            element = await self._create_actionable_element(select, "select")
            if element:
                actionable_elements.append(element)

        # Find additional interactive elements with click handlers
        clickable = await self.page.query_selector_all(
            "[onclick], [role='button'], [role='link'], [role='checkbox'], [role='menuitem']"
        )
        for elem in clickable:
            # Check if element is not already captured (skip duplicates)
            tag_name = await elem.evaluate("el => el.tagName.toLowerCase()")
            if tag_name not in ["button", "a", "input", "select"]:
                element = await self._create_actionable_element(elem, "interactive")
                if element:
                    actionable_elements.append(element)

        return actionable_elements

    async def _create_actionable_element(
        self, element: ElementHandle, element_type: str
    ) -> Optional[ActionableElement]:
        """Create an ActionableElement object from a Playwright ElementHandle.

        Args:
            element (ElementHandle): The Playwright ElementHandle
            element_type (str): The type of element

        Returns:
            Optional[ActionableElement]: The created ActionableElement object, or None if element is invalid
        """
        try:
            # Get element text
            text = await element.text_content() or ""
            text = text.strip()

            # If there's no text, try to get placeholder or value
            if not text:
                placeholder = await element.get_attribute("placeholder")
                value = await element.get_attribute("value")
                text = placeholder or value or ""

            # For links and buttons without text, try to get the title or aria-label
            if not text and (element_type == "link" or element_type == "button"):
                title = await element.get_attribute("title")
                aria_label = await element.get_attribute("aria-label")
                alt = await element.get_attribute("alt")
                text = title or aria_label or alt or ""

            # Get element location and size
            bounding_box = await element.bounding_box()
            if not bounding_box:
                return None  # Element is not visible/rendered

            location = {
                "x": bounding_box["x"],
                "y": bounding_box["y"],
                "width": bounding_box["width"],
                "height": bounding_box["height"],
            }

            # Get all element attributes
            attributes = await element.evaluate(
                """
                el => {
                    const attributes = {};
                    for(let i = 0; i < el.attributes.length; i++) {
                        attributes[el.attributes[i].name] = el.attributes[i].value;
                    }
                    return attributes;
                }
            """
            )

            # Check if element is visible
            is_visible = await element.is_visible()

            # Generate a selector for the element
            selector = await element.evaluate(
                """
                el => {
                    // Try to get a unique ID
                    if (el.id) {
                        return `#${el.id}`;
                    }
                    
                    // Generate a path using classes and other attributes
                    let path = el.tagName.toLowerCase();
                    if (el.className && typeof el.className === 'string') {
                        const classes = el.className.trim().split(/\\s+/);
                        if (classes.length > 0) {
                            path += `.${classes.join('.')}`;
                        }
                    }
                    
                    // Add type for inputs
                    if (el.tagName.toLowerCase() === 'input' && el.type) {
                        path += `[type="${el.type}"]`;
                    }
                    
                    return path;
                }
            """
            )

            return ActionableElement(
                element_type=element_type,
                text=text,
                selector=selector,
                location=location,
                attributes=attributes,
                is_visible=is_visible,
            )
        except Exception as e:
            print(f"Error creating actionable element: {e}")
            return None

    async def export_elements_to_csv(
        self, elements: List[ActionableElement], output_path: str
    ) -> Optional[str]:
        """Export the list of actionable elements to a CSV file.

        Args:
            elements (List[ActionableElement]): List of elements to export
            output_path (str): Path where the CSV should be saved

        Returns:
            Optional[str]: Path to the saved CSV, or None if failed
        """
        try:
            os.makedirs(os.path.dirname(output_path), exist_ok=True)

            # Convert elements to dictionaries
            elements_dicts = []
            for elem in elements:
                elem_dict = asdict(elem)
                # Flatten location dictionary
                location = elem_dict.pop("location")
                elem_dict.update(
                    {
                        "x": location["x"],
                        "y": location["y"],
                        "width": location["width"],
                        "height": location["height"],
                    }
                )
                # Convert attributes dictionary to string to fit in CSV
                elem_dict["attributes"] = json.dumps(elem_dict["attributes"])
                elements_dicts.append(elem_dict)

            # Create DataFrame and save to CSV
            df = pd.DataFrame(elements_dicts)
            df.to_csv(output_path, index=False)
            print(f"Elements exported to {output_path}")
            return output_path
        except Exception as e:
            print(f"Error exporting elements to CSV: {e}")
            return None


async def interact_with_element(scraper, selector, action="click"):
    """Interact with an element using its selector.

    Args:
        scraper (WebScraper): The scraper instance
        selector (str): CSS selector to identify the element
        action (str): Action to perform ("click", "hover", etc.)

    Returns:
        bool: True if interaction was successful, False otherwise
    """
    try:
        element = await scraper.page.query_selector(selector)
        if not element:
            print(f"Element with selector '{selector}' not found")
            return False

        if action == "click":
            await element.click()
            print(f"Clicked element: {selector}")
        elif action == "hover":
            await element.hover()
            print(f"Hovered over element: {selector}")
        elif action.startswith("fill:"):
            text = action.split(":", 1)[1]
            await element.fill(text)
            print(f"Filled element {selector} with text: {text}")
        else:
            print(f"Unsupported action: {action}")
            return False

        return True
    except Exception as e:
        print(f"Error interacting with element {selector}: {e}")
        return False


async def run_scraper(
    url: str,
    output_dir: str,
    headless: bool = True,
    interact: bool = False,
    trace: bool = False,
):
    """Run the web scraper on a URL and save outputs to specified directory.

    Args:
        url (str): URL to scrape
        output_dir (str): Directory to save outputs
        headless (bool): Whether to run browser in headless mode
        interact (bool): Whether to demonstrate interaction with elements
        trace (bool): Whether to record a trace for debugging
    """
    os.makedirs(output_dir, exist_ok=True)

    async with WebScraper(headless=headless, trace=trace) as scraper:
        # Navigate to the page
        success = await scraper.navigate(url)
        if not success:
            print(f"Failed to navigate to {url}")
            return

        # Take a screenshot
        screenshot_path = os.path.join(output_dir, "screenshot.png")
        await scraper.take_screenshot(screenshot_path)

        # Find actionable elements
        elements = await scraper.find_actionable_elements()
        print(f"Found {len(elements)} actionable elements")

        # Export elements to CSV
        csv_path = os.path.join(output_dir, "actionable_elements.csv")
        await scraper.export_elements_to_csv(elements, csv_path)

        # Export elements to JSON (more detailed format)
        json_path = os.path.join(output_dir, "actionable_elements.json")
        with open(json_path, "w") as f:
            json.dump([asdict(elem) for elem in elements], f, indent=2)
        print(f"Elements exported to {json_path}")

        # Print a summary of element types
        element_types = {}
        for elem in elements:
            if elem.element_type not in element_types:
                element_types[elem.element_type] = 0
            element_types[elem.element_type] += 1

        print("\nSummary of actionable elements:")
        for elem_type, count in element_types.items():
            print(f"  {elem_type}: {count}")

        # Demonstrate interaction if requested
        if interact and elements:
            print("\nDemonstrating interaction with elements...")

            # Find a visible link with text to interact with
            demo_element = None
            for elem in elements:
                if elem.is_visible and elem.text and elem.element_type == "link":
                    demo_element = elem
                    break

            if demo_element:
                print(
                    f"Interacting with element: {demo_element.text} ({demo_element.selector})"
                )

                # Take screenshot before interaction
                before_path = os.path.join(output_dir, "before_interaction.png")
                await scraper.take_screenshot(before_path)

                # Perform interaction (hover in this case to avoid navigating away)
                await interact_with_element(scraper, demo_element.selector, "hover")

                # Wait a moment to see the hover effect
                await asyncio.sleep(1)

                # Take screenshot after interaction
                after_path = os.path.join(output_dir, "after_interaction.png")
                await scraper.take_screenshot(after_path)

                print(
                    f"Interaction demonstration complete. Screenshots saved to {before_path} and {after_path}"
                )
            else:
                print("No suitable element found for interaction demonstration")

        if trace:
            trace_path = os.path.join(output_dir, "trace.zip")
            await scraper.context.tracing.stop(path=trace_path)
            print(f"Trace file saved to {trace_path}")


async def run_test_scenario(
    url: str,
    output_dir: str,
    scenario_file: str = None,
    headless: bool = True,
    trace: bool = False,
):
    """Run a test scenario with a sequence of interactions.

    Args:
        url (str): URL to start the test
        output_dir (str): Directory to save outputs
        scenario_file (str): Path to JSON file with test scenario
        headless (bool): Whether to run browser in headless mode
        trace (bool): Whether to record a trace for debugging
    """
    if not scenario_file:
        print("No scenario file provided. Skipping test scenario.")
        return

    try:
        with open(scenario_file, "r") as f:
            scenario = json.load(f)

        print(f"Running test scenario: {scenario.get('name', 'Unnamed scenario')}")

        async with WebScraper(headless=headless, trace=trace) as scraper:
            if trace:
                # Start tracing for debugging
                await scraper.context.tracing.start(screenshots=True, snapshots=True)

            # Navigate to the starting URL
            success = await scraper.navigate(url)
            if not success:
                print(f"Failed to navigate to {url}")
                return

            # Take initial screenshot
            initial_path = os.path.join(output_dir, "scenario_start.png")
            await scraper.take_screenshot(initial_path)

            # Execute each step in the scenario
            for i, step in enumerate(scenario.get("steps", [])):
                step_num = i + 1
                selector = step.get("selector")
                action = step.get("action", "click")
                wait_time = step.get("wait", 1)

                print(f"Step {step_num}: {action} on {selector}")

                # Perform the interaction
                success = await interact_with_element(scraper, selector, action)
                if not success:
                    print(f"Step {step_num} failed. Stopping scenario.")
                    break

                # Wait specified time after action
                await asyncio.sleep(wait_time)

                # Take screenshot after action
                step_path = os.path.join(output_dir, f"scenario_step_{step_num}.png")
                await scraper.take_screenshot(step_path)

            if trace:
                # Stop tracing and save trace file
                trace_path = os.path.join(output_dir, "trace.zip")
                await scraper.context.tracing.stop(path=trace_path)
                print(f"Trace saved to {trace_path}")

            print("Test scenario completed")

    except Exception as e:
        print(f"Error running test scenario: {e}")


def main():
    """Main function to handle command line arguments and execute the scraper."""
    parser = argparse.ArgumentParser(
        description="Web scraper that identifies actionable elements"
    )
    parser.add_argument("url", help="URL to scrape")
    parser.add_argument(
        "--output-dir",
        "-o",
        default=f"scripts/prototypes/output/",
        help="Directory to save outputs",
    )
    parser.add_argument(
        "--visible",
        "-v",
        action="store_false",
        dest="headless",
        help="Run in visible mode (not headless)",
    )
    parser.add_argument(
        "--interact",
        "-i",
        action="store_true",
        help="Demonstrate interaction with a sample element",
    )
    parser.add_argument("--scenario", "-s", help="Path to JSON file with test scenario")
    parser.add_argument(
        "--trace", "-t", action="store_true", help="Record a trace for debugging"
    )
    args = parser.parse_args()

    if args.scenario:
        asyncio.run(
            run_test_scenario(
                args.url, args.output_dir, args.scenario, args.headless, args.trace
            )
        )
    else:
        asyncio.run(
            run_scraper(args.url, args.output_dir, args.headless, args.interact)
        )


if __name__ == "__main__":
    main()
