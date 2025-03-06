import os
import argparse
import json
import asyncio
from dataclasses import dataclass, asdict
from typing import List, Dict, Any, Optional

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
    dom_depth: int = 0  # Depth in the DOM tree
    hierarchy_level: int = 0  # Calculated hierarchy level for testing sequence


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
                url, wait_until="load", timeout=60000  # 60 seconds max
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

        # Calculate hierarchy levels
        actionable_elements = await self.calculate_hierarchy_levels(actionable_elements)

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

            # Calculate the DOM depth of the element
            dom_depth = await element.evaluate(
                """
                el => {
                    let depth = 0;
                    let current = el;
                    while (current.parentElement) {
                        depth++;
                        current = current.parentElement;
                    }
                    return depth;
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
                dom_depth=dom_depth,
                hierarchy_level=0,  # Will be calculated later
            )
        except Exception as e:
            print(f"Error creating actionable element: {e}")
            return None

    async def calculate_hierarchy_levels(
        self, elements: List[ActionableElement]
    ) -> List[ActionableElement]:
        """Calculate hierarchy levels for the elements based on DOM structure,
        parent-child relationships, and semantic importance.

        Args:
            elements (List[ActionableElement]): List of elements to analyze

        Returns:
            List[ActionableElement]: The same elements with hierarchy_level set
        """
        # Step 1: Extract basic page dimensions for normalization
        page_height = await self.page.evaluate("document.body.scrollHeight")
        page_width = await self.page.evaluate("document.body.scrollWidth")

        # Step 2: Calculate overlay score for each element based on DOM structure
        print("Calculating overlay scores for elements...")
        for i, elem in enumerate(elements):
            if not elem.is_visible:
                elem.hierarchy_level = 999  # Very low priority for non-visible elements
                continue

            # Calculate overlay score (now based on DOM structure, not computed styles)
            try:
                # Add a progress indicator every 10 elements to show processing
                if i % 10 == 0:
                    print(f"Processing element {i+1}/{len(elements)}...")

                overlay_score = await self._calculate_z_score(elem.selector)
                elem.attributes["_overlay_score"] = overlay_score
            except Exception as e:
                print(f"Error calculating overlay score: {e}")
                elem.attributes["_overlay_score"] = 0

        # Step 3: Define important action terms
        important_actions = {
            # Critical actions - highest priority, often in modals/overlays
            "critical": [
                "allow all",
                "allow",
                "accept",
                "confirm",
                "deny",
                "reject",
                "continue",
                "proceed",
                "cancel",
            ],
            # Primary actions - high priority
            "primary": [
                "login",
                "sign in",
                "signin",
                "log in",
                "submit",
                "save",
                "start",
            ],
            # Secondary but still important actions
            "secondary": [
                "register",
                "sign up",
                "signup",
                "create account",
                "next",
                "back",
            ],
            # Navigational elements
            "navigation": ["menu", "nav", "navigation", "home"],
            # Search functionality
            "search": ["search", "find", "query"],
        }

        # Function to check if element text matches keywords
        def matches_keywords(text: str, keywords: List[str]) -> bool:
            if not text:
                return False
            text_lower = text.lower()
            return any(keyword in text_lower for keyword in keywords)

        # Step 4: Calculate scores for each element
        print("Calculating priority scores for elements...")
        for elem in elements:
            if elem.hierarchy_level == 999:  # Skip already handled non-visible elements
                continue

            # Start with base score (lower is higher priority)
            score = 100

            # Factor 1: Overlay score is now a major factor
            # Elements in modals/overlays get much higher priority
            overlay_score = elem.attributes.get("_overlay_score", 0)
            if overlay_score > 0:
                # Strong weight for being in overlay, up to 80 points reduction
                score -= min(80, overlay_score * 16)

                # Debug output for overlay elements
                if overlay_score >= 3:
                    print(
                        f"High overlay element: '{elem.text}' (Score: {overlay_score})"
                    )

            # Factor 2: Button text importance
            # Check if this might be an important button based on its text
            if matches_keywords(elem.text, important_actions["critical"]):
                score -= (
                    70  # Critical buttons like "Allow" or "Deny" get very high priority
                )
                print(f"Critical action button: '{elem.text}'")
            elif matches_keywords(elem.text, important_actions["primary"]):
                score -= 60  # Login and primary actions get high priority
            elif matches_keywords(elem.text, important_actions["secondary"]):
                score -= 50  # Registration and secondary actions get good priority
            elif matches_keywords(elem.text, important_actions["navigation"]):
                score -= 30  # Navigation elements
            elif matches_keywords(elem.text, important_actions["search"]):
                score -= 20  # Search functionality

            # Factor 3: Element type priority
            type_scores = {
                "button": 0,  # Buttons are highly interactive
                "link": 5,  # Links are common interactive elements
                "input-text": 10,  # Form inputs less likely to be first interaction
                "select": 10,
                "interactive": 5,  # Other interactive elements (clickable divs, etc.)
            }
            score += type_scores.get(elem.element_type, 10)

            # Factor 4: DOM depth - prefer elements higher in the DOM tree
            # But also consider that overlays may be deeper in the DOM
            if overlay_score < 2:  # For non-overlay elements, shallow DOM is better
                dom_depth_score = min(30, elem.dom_depth * 2)
                score += dom_depth_score

            # Factor 5: Size and visibility factors
            # Calculate element area as percentage of page
            element_area = elem.location["width"] * elem.location["height"]
            page_area = page_width * page_height
            area_ratio = element_area / page_area

            # Penalize extremely small elements (might be hard to click)
            # and extremely large elements (likely containers, not actionable)
            if area_ratio < 0.0005:  # Too small (less than 0.05% of page)
                score += 15
            elif area_ratio > 0.5:  # Too large (more than 50% of page)
                score += 20

            # Store calculated score
            elem.hierarchy_level = max(0, score)  # Ensure no negative scores

        # Step 5: Convert raw scores to hierarchy levels (1-5)
        # Sort elements by score (lower score = higher priority)
        sorted_elements = sorted(elements, key=lambda e: e.hierarchy_level)

        # Assign hierarchy levels
        visible_elements = [e for e in elements if e.hierarchy_level < 999]
        if visible_elements:
            # Get quartile boundaries
            scores = [e.hierarchy_level for e in visible_elements]
            min_score = min(scores)
            max_score = max(scores)
            score_range = max_score - min_score

            if score_range > 0:
                quartile = score_range / 5

                # Assign levels based on score quartiles
                for elem in elements:
                    if elem.hierarchy_level >= 999:
                        elem.hierarchy_level = 5  # Non-visible elements stay at level 5
                    else:
                        # Calculate level (1 is highest priority)
                        relative_score = elem.hierarchy_level - min_score
                        elem.hierarchy_level = min(
                            5, max(1, int(1 + (relative_score / quartile)))
                        )
            else:
                # If all elements have the same score, they're all level 1
                for elem in visible_elements:
                    elem.hierarchy_level = 1

        return elements

    async def _calculate_z_score(self, selector: str) -> float:
        """Calculate a DOM-based overlay score based on element attributes and parent relationships.

        This method looks at DOM structure rather than computed styles to determine if an element
        is likely to be in an overlay/modal.

        Args:
            selector (str): CSS selector for the element

        Returns:
            float: A score representing the element's likelihood of being in an overlay
        """
        try:
            # Script that looks at DOM structure and attributes rather than computed styles
            script = """
                (selector) => {
                    const elem = document.querySelector(selector);
                    if (!elem) return 0;
                    
                    let score = 0;
                    
                    // Function to check if an element or any of its parents match criteria
                    const hasOverlayParent = (el, maxDepth = 5) => {
                        let current = el;
                        let depth = 0;
                        
                        while (current && depth < maxDepth) {
                            // Check element attributes
                            const attrs = current.attributes;
                            const classes = current.className || '';
                            const id = current.id || '';
                            const role = current.getAttribute('role') || '';
                            const tag = current.tagName.toLowerCase();
                            
                            // Check for common overlay classes, IDs, roles
                            const classStr = typeof classes === 'string' ? classes.toLowerCase() : '';
                            const idStr = id.toLowerCase();
                            
                            // Check for modal/dialog related attributes
                            if (
                                role === 'dialog' || 
                                role === 'alertdialog' ||
                                tag === 'dialog' ||
                                current.hasAttribute('aria-modal')
                            ) {
                                return 4;  // Definite dialog
                            }
                            
                            // Check for overlay-related terminology in class/id
                            const overlayTerms = [
                                'modal', 'overlay', 'dialog', 'popup', 'toast', 
                                'notification', 'alert', 'drawer', 'cookie', 
                                'banner', 'consent'
                            ];
                            
                            for (const term of overlayTerms) {
                                if (classStr.includes(term) || idStr.includes(term)) {
                                    return 3;  // Likely overlay
                                }
                            }
                            
                            // Look for fixed position elements through inline style
                            const style = current.style || {};
                            if (style.position === 'fixed') {
                                return 2;  // Fixed position suggests overlay
                            }
                            
                            // Calculate effective z-index through inline style (not computed)
                            if (style.zIndex && parseInt(style.zIndex) > 10) {
                                return 2;  // High z-index suggests overlay
                            }
                            
                            current = current.parentElement;
                            depth++;
                        }
                        
                        return 0;  // No overlay indicators found
                    };
                    
                    // Check if the element itself is a button/link in a form
                    const checkFormAction = (el) => {
                        const tag = el.tagName.toLowerCase();
                        const type = el.getAttribute('type');
                        
                        // Check if this is a form submission element
                        if (
                            (tag === 'button' && (!type || type === 'submit')) ||
                            (tag === 'input' && type === 'submit')
                        ) {
                            // Check if it's in a form
                            let current = el;
                            while (current) {
                                if (current.tagName.toLowerCase() === 'form') {
                                    return 2;  // Form submission button
                                }
                                current = current.parentElement;
                                if (!current) break;
                            }
                        }
                        
                        return 0;
                    };
                    
                    // Check if this appears to be a cookie consent button
                    const checkCookieConsent = (el) => {
                        // Get all text content from element and its children
                        const text = el.textContent.toLowerCase();
                        
                        // Common cookie consent button text
                        const consentTerms = [
                            'accept', 'allow', 'agree', 'consent',
                            'deny', 'reject', 'decline', 'settings', 'preferences',
                            'cookie', 'privacy', 'gdpr', 'ccpa'
                        ];
                        
                        for (const term of consentTerms) {
                            if (text.includes(term)) {
                                // Check if parent might be a cookie banner
                                let parent = el.parentElement;
                                let depth = 0;
                                
                                while (parent && depth < 4) {
                                    const parentText = parent.textContent.toLowerCase();
                                    if (
                                        parentText.includes('cookie') || 
                                        parentText.includes('privacy') ||
                                        parentText.includes('consent') ||
                                        parentText.includes('gdpr') ||
                                        parentText.includes('data')
                                    ) {
                                        return 5;  // Very likely a cookie consent button
                                    }
                                    parent = parent.parentElement;
                                    depth++;
                                }
                                
                                return 2;  // Possible consent-related button
                            }
                        }
                        
                        return 0;
                    };
                    
                    // Main scoring logic
                    score += hasOverlayParent(elem);
                    score += checkFormAction(elem);
                    score += checkCookieConsent(elem);
                    
                    return Math.min(5, score);  // Cap at 5
                }
            """

            # Execute the script
            overlay_score = await self.page.evaluate(script, selector)
            return float(overlay_score)
        except Exception as e:
            print(f"Error calculating overlay score for {selector}: {str(e)[:20]}")
            return 0.0

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

            # Sort elements by hierarchy level
            sorted_elements = sorted(elements, key=lambda e: e.hierarchy_level)

            # Convert elements to dictionaries
            elements_dicts = []
            for elem in sorted_elements:
                # Create a new dict with ordered keys - ensure hierarchy_level is included
                ordered_dict = {
                    "element_type": elem.element_type,
                    "hierarchy_level": elem.hierarchy_level,  # Explicitly include hierarchy_level
                    "dom_depth": elem.dom_depth,
                    "text": elem.text,
                    "selector": elem.selector,
                    "is_visible": elem.is_visible,
                    "x": elem.location["x"],
                    "y": elem.location["y"],
                    "width": elem.location["width"],
                    "height": elem.location["height"],
                    "attributes": json.dumps(elem.attributes),
                }

                elements_dicts.append(ordered_dict)

            # Create DataFrame and save to CSV
            df = pd.DataFrame(elements_dicts)
            df.to_csv(output_path, index=False)
            print(f"Elements exported to {output_path}")

            # Also print the column names to help debug
            print(f"CSV columns: {', '.join(df.columns)}")

            return output_path
        except Exception as e:
            print(f"Error exporting elements to CSV: {e}")
            print(f"Exception details: {str(e)}")
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

        # Debug: Check if hierarchy levels were calculated
        hierarchy_levels = set(elem.hierarchy_level for elem in elements)
        print(f"Hierarchy levels found: {sorted(hierarchy_levels)}")

        # Export elements to CSV
        csv_path = os.path.join(output_dir, "actionable_elements.csv")
        await scraper.export_elements_to_csv(elements, csv_path)

        # Export elements to JSON (more detailed format)
        json_path = os.path.join(output_dir, "actionable_elements.json")
        with open(json_path, "w") as f:
            # Convert to dict and ensure all fields are included
            elements_data = []
            for elem in sorted(elements, key=lambda e: e.hierarchy_level):
                elem_dict = asdict(elem)
                # Ensure hierarchy level is explicitly included
                elements_data.append(elem_dict)

            json.dump(elements_data, f, indent=2)
        print(f"Elements exported to {json_path}")

        # Print a summary of element types and hierarchy levels
        element_types = {}
        hierarchy_counts = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}

        for elem in elements:
            if elem.element_type not in element_types:
                element_types[elem.element_type] = 0
            element_types[elem.element_type] += 1

            if elem.hierarchy_level in hierarchy_counts:
                hierarchy_counts[elem.hierarchy_level] += 1

        print("\nSummary of actionable elements:")
        for elem_type, count in element_types.items():
            print(f"  {elem_type}: {count}")

        print("\nSummary of hierarchy levels:")
        for level, count in hierarchy_counts.items():
            print(f"  Level {level}: {count} elements")

        # Demonstrate interaction if requested
        if interact and elements:
            print("\nDemonstrating interaction with elements...")

            # Find a visible link with text to interact with (preferably Level 1)
            demo_element = None
            for elem in sorted(elements, key=lambda e: e.hierarchy_level):
                if (
                    elem.is_visible
                    and elem.text
                    and elem.element_type == "link"
                    and elem.hierarchy_level == 1
                ):
                    demo_element = elem
                    break

            # Fall back to any visible element if no Level 1 found
            if not demo_element:
                for elem in elements:
                    if elem.is_visible and elem.text and elem.element_type == "link":
                        demo_element = elem
                        break

            if demo_element:
                print(
                    f"Interacting with element: {demo_element.text} (Level: {demo_element.hierarchy_level}, Selector: {demo_element.selector})"
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
        default="prototypes/output",
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
            run_scraper(
                args.url, args.output_dir, args.headless, args.interact, args.trace
            )
        )


if __name__ == "__main__":
    main()
