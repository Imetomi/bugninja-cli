#!/usr/bin/env python3
"""
Web Analyzer - Analyzes web pages and identifies actionable elements.
"""

import os
import json
import asyncio
from dataclasses import dataclass, asdict
from typing import List, Dict, Any, Optional, Union

from playwright.async_api import (
    async_playwright,
    Page,
    ElementHandle,
    Browser,
    BrowserContext,
)


@dataclass
class ActionableElement:
    """Class for storing information about actionable elements on a webpage."""

    element_type: str  # 'button', 'link', 'input', etc.
    text: str  # The text content of the element
    selector: str  # CSS or XPath selector to uniquely identify this element
    location: Dict[str, float]  # x, y coordinates and dimensions
    attributes: Dict[str, Any]  # All HTML attributes of the element
    is_visible: bool  # Whether the element is visible on the page
    dom_depth: int = 0  # Depth in the DOM tree
    hierarchy_level: int = 0  # Calculated hierarchy level for testing sequence


class WebAnalyzer:
    """A web analyzer using Playwright that captures screenshots and identifies actionable elements."""

    def __init__(self, headless: bool = True):
        """Initialize the WebAnalyzer with Playwright settings.

        Args:
            headless (bool): Whether to run the browser in headless mode
        """
        self.headless = headless
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None
        self.elements = []
        self.pages = []
        self.current_goal = ""

    async def start(self):
        """Start the browser and create a new context."""
        self.playwright = await async_playwright().start()

        # Configure browser for better performance
        browser_options = {
            "headless": self.headless,
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
            "ignore_https_errors": True,
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        }

        self.context = await self.browser.new_context(**context_options)

        # Track pages to handle new tabs
        self.pages = []
        self.page = await self.context.new_page()
        self.pages.append(self.page)

        # Listen for new pages
        self.context.on("page", self._handle_new_page)

        return self

    async def _handle_new_page(self, page):
        """Handle new pages (tabs/popups) that are created."""
        print(f"🔄 New page/tab detected!")
        self.pages.append(page)
        # Make the new page the active one
        self.page = page

        # Wait for the page to load
        await page.wait_for_load_state("domcontentloaded")

        # Add same event listener to this page
        page.on("dialog", self._handle_dialog)

    async def stop(self):
        """Close the browser and stop Playwright."""
        if self.context:
            await self.context.close()
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()

    async def navigate_and_analyze(self, url: str) -> bool:
        """Navigate to a URL and analyze the page for actionable elements.

        Args:
            url (str): The URL to navigate to

        Returns:
            bool: True if navigation and analysis were successful
        """
        # Navigate to the URL
        success = await self._navigate(url)
        if not success:
            return False

        # Handle common overlays first
        await self._handle_common_overlays()

        # Find actionable elements
        self.elements = await self._find_actionable_elements()

        return True

    async def _navigate(self, url: str) -> bool:
        """Navigate to the specified URL with improved error handling.

        Args:
            url (str): The URL to navigate to

        Returns:
            bool: True if navigation was successful, False otherwise
        """
        try:
            # Set default timeout
            self.page.set_default_timeout(30000)  # 30 seconds

            # Add dialog handler
            self.page.on("dialog", self._handle_dialog)

            # Set custom headers to avoid bot detection
            await self.page.set_extra_http_headers(
                {
                    "Accept-Language": "en-US,en;q=0.9",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                }
            )

            # Try with different wait_until strategies
            try:
                response = await self.page.goto(url, wait_until="load", timeout=15000)
            except Exception as e:
                print(
                    f"Navigation with 'load' failed, trying with 'domcontentloaded': {e}"
                )
                try:
                    response = await self.page.goto(
                        url, wait_until="domcontentloaded", timeout=15000
                    )
                except Exception as e:
                    print(f"Navigation with 'domcontentloaded' failed: {e}")
                    return False

            # Wait for any possible client-side rendering to complete
            await self.page.wait_for_load_state("domcontentloaded")

            # Additional wait for client-side JS to finish rendering
            await asyncio.sleep(1)

            return response and response.ok
        except Exception as e:
            print(f"Error navigating to {url}: {e}")
            return False

    async def _handle_dialog(self, dialog):
        """Handle JavaScript dialogs (alert, confirm, prompt).

        Args:
            dialog: The dialog object from Playwright
        """
        print(f"🔄 Dialog detected: {dialog.type} - {dialog.message}")

        # Accept all alerts and confirms by default
        if dialog.type in ["alert", "confirm"]:
            await dialog.accept()
        # For prompts, provide an empty string
        elif dialog.type == "prompt":
            await dialog.accept("")
        else:
            await dialog.dismiss()

    async def _handle_common_overlays(self):
        """Handle common overlays like cookie banners and popups before analyzing the page."""
        try:
            # Try multiple strategies to handle cookie banners

            # 1. Try common cookie accept selectors - these are buttons that usually accept cookies
            cookie_accept_selectors = [
                "button:has-text('Accept')",
                "button:has-text('Accept All')",
                "button:has-text('Allow')",
                "button:has-text('Allow All')",
                "button:has-text('Accept Cookies')",
                "button:has-text('I Accept')",
                "button:has-text('Agree')",
                "[id*='accept']:visible",
                "[id*='cookie']:has-text('Accept')",
                "[class*='cookie'] button:first-child",
                "[aria-label*='cookie'] button:first-child",
                "[data-testid*='cookie-accept']",
                "#onetrust-accept-btn-handler",
                ".cc-accept",
                "#consent-accept",
            ]

            # Try each selector
            for selector in cookie_accept_selectors:
                try:
                    # Use waitForSelector with a short timeout to check if the element exists
                    cookie_button = await self.page.wait_for_selector(
                        selector, timeout=500
                    )
                    if cookie_button:
                        print(f"🍪 Found cookie banner: {selector}")
                        await cookie_button.click()
                        # Wait a bit for banner to disappear
                        await asyncio.sleep(1)
                        print("✅ Cookie banner handled")
                        break
                except:
                    # Selector not found, continue to next
                    continue

            # 2. Try to close popups and modals using common close buttons
            close_button_selectors = [
                "button.close",
                "button[aria-label='Close']",
                "[class*='close-button']",
                "[id*='close-button']",
                "button:has-text('×')",
                "button:has-text('Close')",
                "div[role='dialog'] button",
                ".modal button.close",
                "[class*='modal'] button:has-text('Close')",
            ]

            for selector in close_button_selectors:
                try:
                    close_button = await self.page.wait_for_selector(
                        selector, timeout=500
                    )
                    if close_button and await close_button.is_visible():
                        print(f"🔄 Found popup/modal close button: {selector}")
                        await close_button.click()
                        await asyncio.sleep(1)
                        print("✅ Popup/modal closed")
                except:
                    continue

        except Exception as e:
            print(f"Error handling overlays: {e}")
            # Continue anyway, we don't want to fail navigation if overlay handling fails

    def get_current_url(self) -> str:
        """Get the current URL the browser is on.

        Returns:
            str: The current URL
        """
        return self.page.url

    async def go_back(self) -> bool:
        """Go back in browser history.

        Returns:
            bool: True if successfully went back, False otherwise
        """
        try:
            await self.page.go_back()
            await self.page.wait_for_load_state("domcontentloaded")

            # Reanalyze the page
            self.elements = await self._find_actionable_elements()
            return True
        except Exception as e:
            print(f"Error going back: {e}")
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
            return output_path
        except Exception as e:
            print(f"Error taking screenshot: {e}")
            return None

    async def _find_actionable_elements(self) -> List[ActionableElement]:
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
        actionable_elements = await self._calculate_hierarchy_levels(
            actionable_elements
        )

        # Sort elements by hierarchy level, then by y-position (top to bottom)
        return sorted(
            actionable_elements, key=lambda e: (e.hierarchy_level, e.location["y"])
        )

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

    async def _calculate_hierarchy_levels(
        self, elements: List[ActionableElement]
    ) -> List[ActionableElement]:
        """Calculate hierarchy levels for the elements based on DOM structure,
        parent-child relationships, and semantic importance.

        Args:
            elements (List[ActionableElement]): List of elements to analyze

        Returns:
            List[ActionableElement]: The same elements with hierarchy_level set
        """
        try:
            # Step 1: Extract basic page dimensions for normalization
            page_height = await self.page.evaluate("document.body.scrollHeight")
            page_width = await self.page.evaluate("document.body.scrollWidth")

            # Step 2: Calculate overlay score for each element based on DOM structure
            for elem in elements:
                if not elem.is_visible:
                    elem.hierarchy_level = (
                        999  # Very low priority for non-visible elements
                    )
                    continue

                # Calculate overlay score (based on DOM structure)
                try:
                    overlay_score = await self._calculate_overlay_score(elem.selector)
                    elem.attributes["_overlay_score"] = overlay_score
                except Exception as e:
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
                    "sign up",
                    "create",
                    "get started",
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

            # Add login-specific keywords
            auth_keywords = [
                "login",
                "log in",
                "signin",
                "sign in",
                "google",
                "facebook",
                "twitter",
                "github",
                "auth",
                "authenticate",
                "continue with",
            ]

            # Function to check if element text matches keywords
            def matches_keywords(text: str, keywords: List[str]) -> bool:
                if not text:
                    return False
                text_lower = text.lower()
                return any(keyword in text_lower for keyword in keywords)

            # Step 4: Calculate scores for each element
            for elem in elements:
                if (
                    elem.hierarchy_level == 999
                ):  # Skip already handled non-visible elements
                    continue

                # Start with base score (lower is higher priority)
                score = 100

                # Factor 1: Overlay score is now a major factor
                # Elements in modals/overlays get much higher priority
                overlay_score = elem.attributes.get("_overlay_score", 0)
                if overlay_score > 0:
                    # Strong weight for being in overlay, up to 80 points reduction
                    score -= min(80, overlay_score * 16)

                # Factor 2: Button text importance
                # Check if this might be an important button based on its text
                if matches_keywords(elem.text, important_actions["critical"]):
                    score -= 70  # Critical buttons like "Allow" or "Deny" get very high priority
                elif matches_keywords(elem.text, important_actions["primary"]):
                    score -= 60  # Login and primary actions get high priority
                elif matches_keywords(elem.text, important_actions["secondary"]):
                    score -= 50  # Registration and secondary actions get good priority
                elif matches_keywords(elem.text, important_actions["navigation"]):
                    score -= 30  # Navigation elements
                elif matches_keywords(elem.text, important_actions["search"]):
                    score -= 20  # Search functionality

                # Additional scoring for authentication elements
                if elem.text and any(
                    keyword in elem.text.lower() for keyword in auth_keywords
                ):
                    # If the goal is login, give these elements much higher priority
                    score -= 65

                    # Give special preference to Google login if that's the goal
                    if (
                        "google" in elem.text.lower()
                        and hasattr(self, "current_goal")
                        and "google" in self.current_goal.lower()
                    ):
                        score -= (
                            30  # Extra priority for Google auth when that's the goal
                        )

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
            visible_elements = [e for e in elements if e.hierarchy_level < 999]
            if visible_elements:
                scores = [e.hierarchy_level for e in visible_elements]
                min_score = min(scores)
                max_score = max(scores)
                score_range = max_score - min_score

                if score_range > 0:
                    for elem in elements:
                        if elem.hierarchy_level >= 999:
                            elem.hierarchy_level = (
                                5  # Non-visible elements stay at level 5
                            )
                        else:
                            # Convert to 1-5 range (1 is highest priority)
                            normalized = (
                                elem.hierarchy_level - min_score
                            ) / score_range
                            elem.hierarchy_level = int(
                                1 + min(4, normalized * 4)
                            )  # Scale to 1-5
                else:
                    # If all scores are the same, make them all level 3
                    for elem in visible_elements:
                        elem.hierarchy_level = 3

            return elements
        except Exception as e:
            print(f"Error calculating hierarchy levels: {e}")
            # If hierarchy calculation fails, return elements with default level 3
            for elem in elements:
                if elem.hierarchy_level == 0:
                    elem.hierarchy_level = 3
            return elements

    async def _calculate_overlay_score(self, selector: str) -> float:
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
            try:
                overlay_score = await self.page.evaluate(script, selector)
                return float(overlay_score)
            except Exception as e:
                return 0.0
        except Exception as e:
            print(f"Error calculating overlay score for {selector}: {e}")
            return 0.0

    def get_actionable_elements(self) -> List[ActionableElement]:
        """Get the list of actionable elements.

        Returns:
            List[ActionableElement]: The list of actionable elements
        """
        return self.elements

    def set_current_goal(self, goal: str):
        """Set the current navigation goal to help with element prioritization.

        Args:
            goal (str): The goal for the navigation
        """
        self.current_goal = goal

    async def interact_with_element(self, element: ActionableElement) -> bool:
        """Interact with an element with improved handling for navigation events.

        Args:
            element (ActionableElement): The element to interact with

        Returns:
            bool: True if interaction was successful, False otherwise
        """
        try:
            # Find the element
            elem = await self.page.query_selector(element.selector)
            if not elem:
                print(f"Element with selector '{element.selector}' not found")
                return False

            # Scroll element into view and wait a moment
            await elem.scroll_into_view_if_needed()
            await asyncio.sleep(0.5)

            # Check if it's a form input and needs to be filled
            if (
                element.element_type.startswith("input-")
                and element.element_type != "input-checkbox"
                and element.element_type != "input-radio"
            ):
                # Ask user for input value
                input_value = input(
                    f"Enter value for input field '{element.text or element.selector}': "
                )
                await elem.fill(input_value)
                print(f"Filled input {element.selector} with text: {input_value}")
                return True

            # Check if element is likely a Google sign-in button
            is_google_auth = False
            if element.text and any(
                x in element.text.lower() for x in ["google", "sign in with google"]
            ):
                is_google_auth = True
                print("⚠️ Google authentication detected. Special handling enabled.")

            # Store current URL before clicking to detect navigation
            before_url = self.page.url
            before_page_count = len(self.pages)

            print("==================== logs ====================")
            print(f"waiting for navigation until 'domcontentloaded'")
            print("===============================================")

            # Click without waiting for navigation first
            await elem.click()
            print(f"Clicked on element: {element.selector}")

            # Wait a bit for potential new tabs/navigation to start
            await asyncio.sleep(1)

            # Check for new tabs
            if len(self.pages) > before_page_count:
                print(f"🔄 Tab/popup detected! Switched to new tab.")
                # The _handle_new_page event should have switched us to the new page

                # Additional wait for the new page to load
                try:
                    await self.page.wait_for_load_state(
                        "domcontentloaded", timeout=5000
                    )
                except Exception as e:
                    print(f"New page loading wait timed out: {e}")
            else:
                # If no new tab, check if current page is navigating
                try:
                    await self.page.wait_for_load_state(
                        "domcontentloaded", timeout=5000
                    )
                    print("✅ Page load state reached after click")
                except Exception as e:
                    print(f"No navigation state change detected: {e}")

            # Wait additional time for page to stabilize
            await asyncio.sleep(2)

            # Check if URL changed
            after_url = self.page.url
            if after_url != before_url:
                print(f"📍 URL changed to: {after_url}")

                # Compare domains safely - extract domain from URL
                before_domain = (
                    before_url.split("/")[2] if len(before_url.split("/")) > 2 else ""
                )
                after_domain = (
                    after_url.split("/")[2] if len(after_url.split("/")) > 2 else ""
                )

                if before_domain != after_domain:
                    print(f"🔄 External redirection detected: {after_domain}")

            # Special handling for Google auth - extra wait time
            if is_google_auth:
                print("⏳ Waiting longer for Google authentication...")
                await asyncio.sleep(3)

            # Check for cookie banners or popups that might have appeared after clicking
            await self._handle_common_overlays()

            return True

        except Exception as e:
            print(f"Error interacting with element {element.selector}: {e}")
            import traceback

            traceback.print_exc()
            return False
