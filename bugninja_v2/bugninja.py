#!/usr/bin/env python3
"""
BugNinja v2 - Simplified AI-Driven Web Testing Tool
Main implementation
"""

import os
import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any
import traceback
import random
import time

import dotenv
from playwright.async_api import async_playwright, Page, Browser, BrowserContext
from openai import AsyncAzureOpenAI
from playwright_stealth import stealth_sync


class BugNinja:
    """
    BugNinja - AI-Driven Web Testing Tool

    A simplified implementation that follows the core loop:
    1. Start recording for the whole test
    2. While goal is not solved:
       a. Wait for the page to fully load
       b. Gather all elements from the site
       c. Make a request to OpenAI to decide about next steps
       d. Receive decision
       e. Execute decision
    """

    def __init__(
        self,
        headless: bool = True,
        output_dir: str = "./output",
        video_quality: str = "medium",
        goal_confidence: float = 0.8,
    ):
        # Load environment variables
        dotenv.load_dotenv()

        # Configuration
        self.headless = headless
        self.output_dir = Path(output_dir)
        self.video_quality = video_quality
        self.goal_confidence = goal_confidence

        # State
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self.pages: List[Page] = []  # Track all open pages/tabs
        self.step_count = 0
        self.goal_achieved = False
        self.conversation_history = []
        self.last_action = None  # Initialize last_action tracking
        self.cookie_consent_handled = (
            {}
        )  # Track domains where cookie consent has been handled

        # Get all environment variables
        self.env_variables = self._get_environment_variables()

        # Azure OpenAI client
        self.client = AsyncAzureOpenAI(
            api_key=os.getenv("AZURE_OPENAI_API_KEY"),
            api_version="2023-12-01-preview",
            azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
        )

        # Video recording settings
        self.video_settings = {
            "low": {"width": 800, "height": 600},
            "medium": {"width": 1280, "height": 720},
            "high": {"width": 1920, "height": 1080},
        }

        # Create output directory
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def _get_environment_variables(self):
        """
        Get all environment variables, categorized by type
        Returns a dictionary with categories of variables
        """
        # Get all environment variables
        all_vars = dict(os.environ)

        # Define categories and their detection patterns
        categories = {
            "credentials": [
                "PASSWORD",
                "PWD",
                "SECRET",
                "TOKEN",
                "KEY",
                "AUTH",
                "LOGIN",
                "PASS",
                "CREDENTIAL",
                "APIKEY",
                "API_KEY",
            ],
            "user_info": [
                "EMAIL",
                "USERNAME",
                "USER",
                "NAME",
                "PHONE",
                "MOBILE",
                "ADDRESS",
                "ACCOUNT",
                "ID",
                "IDENTITY",
            ],
            "config": [
                "ENDPOINT",
                "URL",
                "HOST",
                "PORT",
                "PATH",
                "DOMAIN",
                "CONFIG",
                "SETTING",
                "ENV",
                "ENVIRONMENT",
                "MODE",
            ],
        }

        # Initialize result with an "other" category for uncategorized vars
        result = {"credentials": {}, "user_info": {}, "config": {}, "other": {}}

        # Skip these internal environment variables
        skip_vars = [
            "PYTHONPATH",
            "PATH",
            "SHELL",
            "TERM",
            "USER",
            "HOME",
            "TMPDIR",
            "TEMP",
            "TMP",
            "LANG",
            "LC_ALL",
            "DISPLAY",
        ]

        # Categorize each environment variable
        for name, value in all_vars.items():
            # Skip internal environment variables
            if name in skip_vars or name.startswith("_"):
                continue

            # Determine category
            categorized = False
            for category, patterns in categories.items():
                for pattern in patterns:
                    if pattern in name.upper():
                        result[category][name] = value
                        categorized = True
                        break
                if categorized:
                    break

            # If not categorized, put in "other"
            if not categorized:
                result["other"][name] = value

        return result

    def _is_sensitive_variable(self, var_name):
        """Check if a variable name suggests it contains sensitive information"""
        sensitive_patterns = [
            "PASSWORD",
            "PWD",
            "SECRET",
            "TOKEN",
            "KEY",
            "AUTH",
            "CREDENTIAL",
            "APIKEY",
            "API_KEY",
            "PRIVATE",
        ]

        var_upper = var_name.upper()
        return any(pattern in var_upper for pattern in sensitive_patterns)

    async def start(self):
        """Start the browser and set up recording"""
        # Initialize Playwright
        playwright = await async_playwright().start()

        # Launch browser with additional arguments to reduce fingerprinting
        self.browser = await playwright.chromium.launch(
            headless=self.headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-features=IsolateOrigins,site-per-process",
                "--disable-site-isolation-trials",
                "--disable-infobars",
                "--disable-automation",
                "--disable-blink-features",
                "--no-sandbox",
                "--disable-extensions",
                "--disable-default-apps",
                "--disable-popup-blocking",
                "--disable-background-timer-throttling",
                "--disable-backgrounding-occluded-windows",
                "--disable-renderer-backgrounding",
                "--disable-device-discovery-notifications",
                "--disable-web-security",
                "--disable-features=IsolateOrigins,site-per-process,TranslateUI",
                "--disable-site-isolation-trials",
                "--disable-features=BlockInsecurePrivateNetworkRequests",
                "--disable-features=CrossSiteDocumentBlockingIfIsolating",
                "--disable-features=CrossSiteDocumentBlockingAlways",
            ],
        )

        # Create browser context with video recording and additional options to appear more human-like
        video_size = self.video_settings.get(
            self.video_quality, self.video_settings["medium"]
        )

        # Generate a more realistic user agent
        user_agents = [
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",
        ]
        selected_user_agent = random.choice(user_agents)

        # Generate a realistic viewport size
        viewport_sizes = [
            {"width": 1920, "height": 1080},
            {"width": 1680, "height": 1050},
            {"width": 1440, "height": 900},
            {"width": 1366, "height": 768},
        ]
        selected_viewport = random.choice(viewport_sizes)

        # Generate a realistic timezone
        timezones = [
            "America/New_York",
            "America/Los_Angeles",
            "Europe/London",
            "Europe/Paris",
            "Asia/Tokyo",
        ]
        selected_timezone = random.choice(timezones)

        self.context = await self.browser.new_context(
            record_video_dir=str(self.output_dir),
            record_video_size=video_size,
            viewport=selected_viewport,
            user_agent=selected_user_agent,
            locale="en-US",
            timezone_id=selected_timezone,
            has_touch=False,
            is_mobile=False,
            color_scheme="light",
            reduced_motion="no-preference",
            java_script_enabled=True,
            ignore_https_errors=True,
            extra_http_headers={
                "Accept-Language": "en-US,en;q=0.9",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
                "Accept-Encoding": "gzip, deflate, br",
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "none",
                "Sec-Fetch-User": "?1",
                "Upgrade-Insecure-Requests": "1",
                "sec-ch-ua": '"Chromium";v="120", "Google Chrome";v="120", "Not-A.Brand";v="99"',
                "sec-ch-ua-mobile": "?0",
                "sec-ch-ua-platform": '"macOS"',
            },
            permissions=["geolocation", "notifications"],
        )

        # Set up event listeners for new pages and page closures
        self.context.on("page", self._handle_new_page)

        # Create a new page
        self.page = await self.context.new_page()
        self.pages.append(self.page)

        # Set up page-specific event handlers
        await self._setup_page_event_handlers(self.page)

        # Apply additional fingerprint protection
        await self.add_browser_fingerprint_protection()

        print("🚀 Browser started with enhanced anti-detection measures")

    async def _handle_new_page(self, page):
        """Handle a new page/tab being opened"""
        print("🔄 New tab/window detected")
        self.pages.append(page)

        # Set up event handlers for the new page
        await self._setup_page_event_handlers(page)

        # Switch to the new page
        self.page = page
        print(f"👉 Switched to new tab: {page.url}")

    async def _setup_page_event_handlers(self, page):
        """Set up event handlers for a page"""
        # Handle page close events
        page.on("close", lambda: asyncio.create_task(self._handle_page_close(page)))

        # Handle dialog events (alerts, confirms, prompts)
        page.on(
            "dialog", lambda dialog: asyncio.create_task(self._handle_dialog(dialog))
        )

        # Apply stealth mode to the page
        stealth_sync(page)
        print("🛡️ Applied stealth mode to page")

    async def _handle_page_close(self, closed_page):
        """Handle a page/tab being closed"""
        print("🔄 Tab/window closed")

        # Remove the closed page from our list
        if closed_page in self.pages:
            self.pages.remove(closed_page)

        # If the current page was closed, switch to another open page
        if self.page == closed_page and self.pages:
            # Switch to the most recently opened page
            self.page = self.pages[-1]
            print(f"👉 Switched to tab: {self.page.url}")
        elif not self.pages:
            # If no pages are left, create a new one
            print("⚠️ No tabs left, creating a new one")
            self.page = await self.context.new_page()
            self.pages.append(self.page)
            await self._setup_page_event_handlers(self.page)

    async def _handle_dialog(self, dialog):
        """Handle JavaScript dialogs (alert, confirm, prompt)"""
        message = dialog.message
        dialog_type = dialog.type

        print(f"🤖 Dialog detected: {dialog_type} - {message}")

        # Accept all dialogs by default
        await dialog.accept()

    async def stop(self):
        """Stop the browser and finalize recording"""
        if self.context:
            await self.context.close()
        if self.browser:
            await self.browser.close()
        print("👋 Browser closed and video saved")

    async def wait_for_page_load(self):
        """Wait for the page to be fully loaded"""
        try:
            # Wait for network to be idle (no more than 2 connections for at least 500 ms)
            await self.page.wait_for_load_state("networkidle", timeout=10000)
        except Exception:
            # Fallback: wait for DOM content to be loaded
            await self.page.wait_for_load_state("domcontentloaded")
            # Additional small delay to ensure JS has run
            await asyncio.sleep(1)

        print("📄 Page fully loaded")

    async def gather_page_elements(self):
        """Gather all interactive elements from the page"""
        try:
            # Check if cookie consent has already been handled for this domain
            current_domain = (
                self.page.url.split("/")[2]
                if self.page.url.startswith("http")
                else None
            )
            cookie_already_handled = current_domain and self.cookie_consent_handled.get(
                current_domain, False
            )

            # Get all interactive elements from the page
            elements = await self.page.evaluate(
                """(skipCookieDetection) => {
                // Helper function to get text content
                function getTextContent(element) {
                    // Get direct text content (excluding child elements)
                    let text = '';
                    for (const node of element.childNodes) {
                        if (node.nodeType === Node.TEXT_NODE) {
                            text += node.textContent.trim();
                        }
                    }
                    
                    // If no direct text, get all text content
                    if (!text.trim()) {
                        text = element.textContent.trim();
                    }
                    
                    return text;
                }
                
                // Helper function to get parent text
                function getParentText(element) {
                    if (!element.parentElement) return '';
                    
                    // Get text from parent, excluding the current element's text
                    const parent = element.parentElement;
                    const clone = parent.cloneNode(true);
                    
                    // Remove the current element from the clone
                    for (const child of clone.children) {
                        if (child.outerHTML === element.outerHTML) {
                            clone.removeChild(child);
                            break;
                        }
                    }
                    
                    return clone.textContent.trim();
                }
                
                // Helper function to get surrounding text
                function getSurroundingText(element) {
                    // Get text from siblings
                    let surroundingText = '';
                    if (element.parentElement) {
                        for (const sibling of element.parentElement.children) {
                            if (sibling !== element) {
                                surroundingText += sibling.textContent.trim() + ' ';
                            }
                        }
                    }
                    return surroundingText.trim();
                }
                
                // Helper function to check if an element is visible
                function isVisible(element) {
                    if (!element.getBoundingClientRect) return false;
                    
                    const rect = element.getBoundingClientRect();
                    const style = window.getComputedStyle(element);
                    
                    return rect.width > 0 && 
                           rect.height > 0 && 
                           style.display !== 'none' && 
                           style.visibility !== 'hidden' && 
                           parseFloat(style.opacity) > 0;
                }
                
                // Helper function to check if an element is likely interactive
                function isLikelyInteractive(element) {
                    // Check tag name
                    const tag = element.tagName.toLowerCase();
                    if (['a', 'button', 'input', 'select', 'textarea', 'label', 'summary'].includes(tag)) {
                        return true;
                    }
                    
                    // Check role attribute
                    const role = element.getAttribute('role');
                    if (role && ['button', 'link', 'checkbox', 'menuitem', 'tab', 'radio'].includes(role)) {
                        return true;
                    }
                    
                    // Check for click event listeners (approximate)
                    if (element.onclick || element.getAttribute('onclick')) {
                        return true;
                    }
                    
                    // Check for common interactive class names
                    const classAttr = element.getAttribute('class') || '';
                    if (classAttr.match(/button|btn|clickable|selectable|link|nav-item|menu-item/i)) {
                        return true;
                    }
                    
                    // Check for cursor style
                    const style = window.getComputedStyle(element);
                    if (style.cursor === 'pointer') {
                        return true;
                    }
                    
                    // Check for tabindex
                    if (element.hasAttribute('tabindex') && element.getAttribute('tabindex') >= 0) {
                        return true;
                    }
                    
                    return false;
                }
                
                // Helper function to check if an element might be a cookie consent button
                function isCookieConsentElement(element) {
                    if (skipCookieDetection) return false;
                    
                    // Check text content
                    const text = (element.textContent || '').toLowerCase();
                    const cookieTerms = ['cookie', 'consent', 'accept', 'agree', 'allow', 'privacy', 'gdpr', 'ccpa', 'az összes elfogadása'];
                    
                    if (cookieTerms.some(term => text.includes(term))) {
                        return true;
                    }
                    
                    // Check attributes
                    const id = (element.id || '').toLowerCase();
                    const className = (element.className || '').toLowerCase();
                    const ariaLabel = (element.getAttribute('aria-label') || '').toLowerCase();
                    
                    if (cookieTerms.some(term => id.includes(term) || className.includes(term) || ariaLabel.includes(term))) {
                        return true;
                    }
                    
                    // Check parent elements for cookie-related content
                    let parent = element.parentElement;
                    for (let i = 0; i < 3 && parent; i++) { // Check up to 3 levels up
                        const parentText = (parent.textContent || '').toLowerCase();
                        if (cookieTerms.some(term => parentText.includes(term))) {
                            return true;
                        }
                        parent = parent.parentElement;
                    }
                    
                    return false;
                }
                
                // Selectors for interactive elements
                const selectors = [
                    // Basic interactive elements
                    'a', 'button', 'input', 'select', 'textarea', 'summary',
                    
                    // Elements with interactive roles
                    '[role="button"]', '[role="link"]', '[role="checkbox"]', 
                    '[role="menuitem"]', '[role="tab"]', '[role="radio"]',
                    
                    // Elements that look interactive
                    '[onclick]', '[tabindex]', '.btn', '.button',
                ];
                
                // Add cookie-related selectors only if we haven't handled cookies yet
                if (!skipCookieDetection) {
                    selectors.push(
                        '[class*="cookie"]', '[id*="cookie"]',
                        '[class*="consent"]', '[id*="consent"]',
                        '[class*="privacy"]', '[id*="privacy"]',
                        '[class*="accept"]', '[class*="agree"]',
                        '[aria-label*="cookie"]', '[aria-label*="consent"]',
                        '[title*="cookie"]', '[title*="consent"]'
                    );
                }
                
                // Get all elements matching our selectors
                const elements = [];
                const seen = new Set();
                
                for (const selector of selectors) {
                    try {
                        const found = document.querySelectorAll(selector);
                        for (const element of found) {
                            // Skip if already processed or not visible
                            if (seen.has(element) || !isVisible(element)) continue;
                            seen.add(element);
                            
                            // Get element properties
                            const rect = element.getBoundingClientRect();
                            const tag = element.tagName.toLowerCase();
                            
                            // Skip elements that are too small to be interactive
                            if (rect.width < 5 || rect.height < 5) continue;
                            
                            // Get element attributes
                            const id = element.id || '';
                            const classAttr = element.getAttribute('class') || '';
                            const type = element.getAttribute('type') || '';
                            const name = element.getAttribute('name') || '';
                            const placeholder = element.getAttribute('placeholder') || '';
                            const value = element.getAttribute('value') || '';
                            const href = element.getAttribute('href') || '';
                            const ariaLabel = element.getAttribute('aria-label') || '';
                            const ariaRole = element.getAttribute('role') || '';
                            const title = element.getAttribute('title') || '';
                            
                            // Get text content
                            const text = getTextContent(element);
                            const parentText = getParentText(element);
                            const surroundingText = getSurroundingText(element);
                            
                            // Check if this is likely an interactive element
                            const isInteractive = isLikelyInteractive(element);
                            
                            // Check if this might be a cookie consent element (only if not already handled)
                            const isCookieConsent = isCookieConsentElement(element);
                            
                            // Add to our list
                            elements.push({
                                id: elements.length,
                                tag,
                                x: rect.left,
                                y: rect.top,
                                width: rect.width,
                                height: rect.height,
                                id_attr: id,
                                class_attr: classAttr,
                                type,
                                name,
                                placeholder,
                                value,
                                href,
                                text,
                                parent_text: parentText,
                                surrounding_text: surroundingText,
                                aria_label: ariaLabel,
                                aria_role: ariaRole,
                                title,
                                is_likely_interactive: isInteractive,
                                is_cookie_consent: isCookieConsent
                            });
                        }
                    } catch (e) {
                        // Skip errors for individual selectors
                        console.error(`Error with selector ${selector}: ${e.message}`);
                    }
                }
                
                // Sort elements by position (top to bottom, left to right)
                elements.sort((a, b) => {
                    // Group elements that are roughly on the same "row"
                    const rowThreshold = 20; // pixels
                    if (Math.abs(a.y - b.y) < rowThreshold) {
                        return a.x - b.x; // Same row, sort left to right
                    }
                    return a.y - b.y; // Different rows, sort top to bottom
                });
                
                return elements;
            }""",
                cookie_already_handled,
            )

            # Filter out elements that are outside the viewport
            viewport_size = await self.page.evaluate(
                """() => {
                return {
                    width: window.innerWidth,
                    height: window.innerHeight
                }
            }"""
            )

            visible_elements = [
                e
                for e in elements
                if e["x"] < viewport_size["width"]
                and e["y"] < viewport_size["height"]
                and e["x"] + e["width"] > 0
                and e["y"] + e["height"] > 0
            ]

            # Prioritize cookie consent elements
            cookie_elements = [
                e for e in visible_elements if e.get("is_cookie_consent", False)
            ]
            other_elements = [
                e for e in visible_elements if not e.get("is_cookie_consent", False)
            ]

            # Reorder elements to put cookie consent elements first
            prioritized_elements = cookie_elements + other_elements

            # Reassign IDs to maintain sequential ordering
            for i, element in enumerate(prioritized_elements):
                element["id"] = i

            print(f"🔍 Found {len(prioritized_elements)} interactive elements")

            # Log cookie consent elements if found
            if cookie_elements:
                print(
                    f"🍪 Found {len(cookie_elements)} potential cookie consent elements"
                )
                for e in cookie_elements[:3]:  # Show up to 3 examples
                    desc = self._get_element_description(e)
                    print(f"  - {desc}")
                if len(cookie_elements) > 3:
                    print(f"  - ... and {len(cookie_elements) - 3} more")

            return prioritized_elements

        except Exception as e:
            print(f"⚠️ Error gathering page elements: {e}")
            traceback.print_exc()
            return []

    async def take_screenshot(self):
        """Take a screenshot of the current page"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        screenshot_path = self.output_dir / f"step_{self.step_count}_{timestamp}.png"
        await self.page.screenshot(path=screenshot_path)
        return screenshot_path

    async def ask_ai_for_decision(self, screenshot_path, elements, goal, url):
        """Ask Azure OpenAI for the next action to take"""
        # Prepare system message
        system_message = """You are an AI end-to-end web tester that helps users accomplish tasks on websites.
Your job is to analyze the current webpage and decide what action to take next to achieve the user's goal.

IMPORTANT PRIORITIES:
1. ALWAYS handle cookie banners and privacy prompts first before anything else! Look for buttons with text like "Accept", "Accept All", "I Agree", "Agree", "Allow", "Continue", "OK", "Got it", etc.
2. If you are provided with a login form, use the provided credentials when appropriate, this could be also part of a testing journey on many websites. In some cases you maybe have register a new account. You can use made-up information with John Doe to fill up the form.
3. Focus on the main task after handling popups and logins
4. Try to examine multiple options if the first try didn't work in a previous step for a specific task.
5. Evaluate if the goal has been achieved after each step

COOKIE CONSENT GUIDANCE:
When dealing with cookie consent banners:
1. Look for buttons with text like "Accept All", "Accept", "Agree", "I Agree", "Allow All", etc.
2. Pay attention to the surrounding text and context of buttons
3. If there are multiple options, prefer the one that accepts all cookies to proceed quickly
4. If you can't find a specific accept button, look for a button with a checkmark or "OK" or "Continue"
5. Cookie banners often appear at the top or bottom of the page, or as modal dialogs

SEARCH OPERATION GUIDANCE:
When performing search operations:
1. First identify the search input field and type the search query
2. After typing, look for a search button or submit button to click
3. If no button is visible, the system will automatically press Enter after typing in search fields
4. Do not repeatedly click on the same search field - instead look for a submit button or suggest pressing Enter
5. Search forms typically have a magnifying glass icon or a button labeled "Search" or "Go"

For each step, you will:
1. Analyze the screenshot of the current webpage
2. Choose ONE element to interact with (click or type)
3. Specify exactly what to do with that element
4. Explain your reasoning
5. Indicate if you believe the goal has been achieved

ELEMENT IDENTIFICATION GUIDANCE:
When identifying elements, provide as much descriptive information as possible:
1. Include a clear element_description that describes what the element is (e.g., "search input field", "submit button")
2. For search operations, explicitly mention "search" in your descriptions
3. If targeting a specific input field, mention its purpose (e.g., "email input", "password field")
4. If you see a specific ID, class, or placeholder text in the element, include that in your reasoning
5. Describe the visual characteristics and location of the element when possible

REMEMBER, ALWAYS ACCEPT COOKIE BANNERS AND PRIVACY PROMPTS FIRST BEFORE ANYTHING ELSE!

Respond in JSON format with these fields:
- action: "click" or "type"
- element_id: ID of the element to interact with
- element_description: Detailed description of what the element is and its purpose
- input_text: Text to type (only for "type" actions)
- reasoning: Brief explanation of your decision
- goal_achieved: true/false whether the goal has been completed
- confidence: 0.0-1.0 indicating your confidence that the goal is achieved
"""

        # Get information about all open tabs
        open_tabs = []
        for i, p in enumerate(self.pages):
            try:
                tab_url = p.url
                tab_title = await p.title()
                is_current = p == self.page
                open_tabs.append(
                    {
                        "index": i,
                        "url": tab_url,
                        "title": tab_title,
                        "is_current": is_current,
                    }
                )
            except:
                # Skip tabs that might have closed or are in an error state
                continue

        # Prepare user message
        user_message = f"""
Current URL: {url}
Step: {self.step_count}
Goal: {goal}

Open tabs: {json.dumps(open_tabs)}
"""

        # Add information about available environment variables by category
        # For credentials, only show the names, not the values
        if self.env_variables["credentials"]:
            credential_names = list(self.env_variables["credentials"].keys())
            user_message += f"Available credentials: {', '.join(credential_names)}\n"

        # For user info, show names and values if not sensitive
        if self.env_variables["user_info"]:
            user_info_str = []
            for name, value in self.env_variables["user_info"].items():
                if not self._is_sensitive_variable(name):
                    user_info_str.append(f"{name}: {value}")
                else:
                    user_info_str.append(f"{name}: [REDACTED]")
            user_message += f"User information: {', '.join(user_info_str)}\n"

        # For other relevant variables, show names and values if not sensitive
        other_vars = {}
        other_vars.update(self.env_variables["config"])
        other_vars.update(self.env_variables["other"])
        if other_vars:
            other_vars_str = []
            for name, value in other_vars.items():
                if not self._is_sensitive_variable(name):
                    other_vars_str.append(f"{name}: {value}")
                else:
                    other_vars_str.append(f"{name}: [REDACTED]")
            user_message += f"Other variables: {', '.join(other_vars_str)}\n"

        # Add enhanced element information
        user_message += "\nInteractive Elements:\n"

        # Check for potential cookie consent elements first
        cookie_elements = []
        for element in elements:
            text = element.get("text", "").lower()
            class_attr = element.get("class_attr", "").lower()
            id_attr = element.get("id_attr", "").lower()
            aria_label = element.get("aria_label", "").lower()
            title = element.get("title", "").lower()
            parent_text = element.get("parent_text", "").lower()
            surrounding_text = element.get("surrounding_text", "").lower()

            # Check if this might be a cookie-related element
            cookie_related_terms = [
                "cookie",
                "consent",
                "accept",
                "agree",
                "allow",
                "privacy",
                "gdpr",
                "ccpa",
            ]
            is_cookie_related = any(
                term in text
                or term in class_attr
                or term in id_attr
                or term in aria_label
                or term in title
                or term in parent_text
                or term in surrounding_text
                for term in cookie_related_terms
            )

            if is_cookie_related and element.get("is_likely_interactive", False):
                cookie_elements.append(element)

        # If we found potential cookie elements, highlight them
        if cookie_elements:
            user_message += "\nPotential Cookie Consent Elements:\n"
            for element in cookie_elements:
                desc = self._get_element_description(element)
                user_message += f"- Element #{element['id']}: {desc}\n"
                user_message += f"  Text: '{element['text']}'\n"
                if element["parent_text"]:
                    user_message += f"  Parent Text: '{element['parent_text']}'\n"
                if element["surrounding_text"]:
                    user_message += (
                        f"  Surrounding Text: '{element['surrounding_text']}'\n"
                    )
                if element["aria_label"]:
                    user_message += f"  Aria Label: '{element['aria_label']}'\n"
                if element["title"]:
                    user_message += f"  Title: '{element['title']}'\n"
                user_message += "\n"

        # Group elements by type for better organization
        input_elements = []
        button_elements = []
        link_elements = []
        other_elements = []

        for element in elements:
            if element in cookie_elements:
                continue  # Skip elements already listed in cookie elements

            if element["tag"] == "input" or element["tag"] == "textarea":
                input_elements.append(element)
            elif (
                element["tag"] == "button"
                or "button" in element["class_attr"].lower()
                or element["aria_role"] == "button"
            ):
                button_elements.append(element)
            elif element["tag"] == "a" or element["aria_role"] == "link":
                link_elements.append(element)
            else:
                other_elements.append(element)

        # Add search-related elements first (highest priority)
        search_elements = []
        for element in elements:
            if element in cookie_elements:
                continue  # Skip elements already listed in cookie elements

            is_search = (
                element["type"] == "search"
                or "search" in (element["id_attr"] or "").lower()
                or "search" in (element["name"] or "").lower()
                or "search" in (element["placeholder"] or "").lower()
                or "search" in (element["aria_label"] or "").lower()
                or element["aria_role"] == "search"
                or element["aria_role"] == "searchbox"
            )
            if is_search:
                search_elements.append(element)

        if search_elements:
            user_message += "\nSearch Elements:\n"
            for element in search_elements:
                desc = self._get_element_description(element)
                attrs = []
                if element["id_attr"]:
                    attrs.append(f"id='{element['id_attr']}'")
                if element["placeholder"]:
                    attrs.append(f"placeholder='{element['placeholder']}'")
                if element["name"]:
                    attrs.append(f"name='{element['name']}'")
                if element["aria_label"]:
                    attrs.append(f"aria-label='{element['aria_label']}'")

                user_message += (
                    f"- Element #{element['id']}: {desc} ({', '.join(attrs)})\n"
                )

        # Add input fields
        if input_elements:
            user_message += "\nInput Elements:\n"
            for element in input_elements:
                if element in search_elements:
                    continue  # Skip if already listed in search elements
                desc = self._get_element_description(element)
                attrs = []
                if element["id_attr"]:
                    attrs.append(f"id='{element['id_attr']}'")
                if element["placeholder"]:
                    attrs.append(f"placeholder='{element['placeholder']}'")
                if element["name"]:
                    attrs.append(f"name='{element['name']}'")
                if element["type"]:
                    attrs.append(f"type='{element['type']}'")

                user_message += (
                    f"- Element #{element['id']}: {desc} ({', '.join(attrs)})\n"
                )
                if element["parent_text"]:
                    user_message += f"  Parent Text: '{element['parent_text']}'\n"

        # Add buttons
        if button_elements:
            user_message += "\nButton Elements:\n"
            for element in button_elements:
                desc = self._get_element_description(element)
                user_message += f"- Element #{element['id']}: {desc}\n"
                if element["text"]:
                    user_message += f"  Text: '{element['text']}'\n"
                if element["aria_label"]:
                    user_message += f"  Aria Label: '{element['aria_label']}'\n"
                if element["title"]:
                    user_message += f"  Title: '{element['title']}'\n"

        # Add links
        if link_elements:
            user_message += "\nLink Elements:\n"
            for element in link_elements:
                desc = self._get_element_description(element)
                user_message += f"- Element #{element['id']}: {desc}\n"
                if element["text"]:
                    user_message += f"  Text: '{element['text']}'\n"
                if element["href"]:
                    user_message += f"  Href: '{element['href']}'\n"

        # Add other interactive elements
        if other_elements:
            user_message += "\nOther Interactive Elements:\n"
            for element in other_elements:
                desc = self._get_element_description(element)
                user_message += f"- Element #{element['id']}: {desc}\n"
                if element["text"]:
                    user_message += f"  Text: '{element['text']}'\n"

        # Add a note about element identification
        user_message += "\nNOTE: When referring to elements, provide detailed descriptions to help with identification. For search operations, explicitly mention 'search' in your element_description."
        user_message += "\nREMEMBER: If you see a cookie consent banner or privacy prompt, handle that FIRST before proceeding with the main task."

        # Encode the screenshot
        image_base64 = self._encode_image(screenshot_path)

        # Add the conversation history to provide context
        messages = [
            {"role": "system", "content": system_message},
        ]

        # Add conversation history (last 3 exchanges)
        for msg in self.conversation_history[-6:]:
            messages.append(msg)

        # Add the current user message
        messages.append(
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": user_message},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{image_base64}"},
                    },
                ],
            }
        )

        # Add elements as a separate message
        messages.append(
            {
                "role": "user",
                "content": f"Here are the interactive elements on the page: {json.dumps(elements)}",
            }
        )

        # Add all environment variables as a separate message (not logged)
        # This ensures the AI has access to all variables but they're not stored in conversation history
        env_vars_message = {
            "credentials": self.env_variables["credentials"],
            "user_info": self.env_variables["user_info"],
            "config": self.env_variables["config"],
            "other": self.env_variables["other"],
        }
        messages.append(
            {
                "role": "user",
                "content": f"Use these environment variables when needed: {json.dumps(env_vars_message)}",
            }
        )

        # Make the API call
        response = await self.client.chat.completions.create(
            model=os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME", "gpt-4o"),
            messages=messages,
            response_format={"type": "json_object"},
            max_tokens=1000,
        )

        # Parse the response
        response_content = response.choices[0].message.content

        # Store the exchange in conversation history (without credentials)
        self.conversation_history.append({"role": "user", "content": user_message})
        self.conversation_history.append(
            {"role": "assistant", "content": response_content}
        )

        try:
            decision = json.loads(response_content)

            # Get element description for better logging
            element = next(
                (e for e in elements if e["id"] == decision.get("element_id")), None
            )
            element_desc = (
                self._get_element_description(element) if element else "Unknown element"
            )

            # Log the decision with better description
            action = decision.get("action", "click")
            if action == "click":
                print(
                    f"🤖 AI decision: {action} on element #{decision.get('element_id')}: {element_desc}"
                )
            elif action == "type":
                input_text = decision.get("input_text", "")
                # Check if this is sensitive information
                is_sensitive = element and self._is_sensitive_field(element)

                if is_sensitive:
                    print(
                        f"🤖 AI decision: {action} [REDACTED] into element #{decision.get('element_id')}: {element_desc}"
                    )
                else:
                    print(
                        f"🤖 AI decision: {action} '{input_text}' into element #{decision.get('element_id')}: {element_desc}"
                    )

            print(f"💭 Reasoning: {decision.get('reasoning', 'No reasoning provided')}")

            # Check if goal is achieved
            if (
                decision.get("goal_achieved", False)
                and decision.get("confidence", 0) >= self.goal_confidence
            ):
                self.goal_achieved = True
                print(
                    f"🎉 Goal achieved with confidence {decision.get('confidence', 0):.2f} (threshold: {self.goal_confidence:.2f})"
                )
                print(
                    f"💭 Reasoning: {decision.get('reasoning', 'No reasoning provided')}"
                )
                return decision

            return decision
        except json.JSONDecodeError:
            print("⚠️ Failed to parse AI response as JSON")
            print(f"Raw response: {response_content}")
            # Return a default decision as fallback
            return {
                "action": "click",
                "element_id": 0,  # First element as fallback
                "input_text": "",
                "reasoning": "Fallback decision due to parsing error",
                "goal_achieved": False,
                "confidence": 0.0,
            }

    async def execute_decision(self, decision, elements):
        """Execute the decision made by the AI"""
        try:
            element_id = decision.get("element_id")
            action = decision.get("action", "click")

            # Find the element using our fallback strategy
            element = self._find_element_with_fallback(element_id, decision, elements)

            # Track the last action for better decision making
            current_action = {"element_id": element_id, "action": action}

            # Get current domain to track cookie consent
            current_domain = (
                self.page.url.split("/")[2]
                if self.page.url.startswith("http")
                else None
            )

            # If this is a cookie consent element and the action is successful, mark it as handled
            if element and element.get("is_cookie_consent") and current_domain:
                self.cookie_consent_handled[current_domain] = True
                print(
                    f"🍪 Marking cookie consent as handled for domain: {current_domain}"
                )

            # Handle direct selector case (when element has is_direct_selector flag)
            if element and element.get("is_direct_selector"):
                print(
                    f"🔍 Attempting to click element with direct selector: #{element['id_attr']}"
                )

                # Try multiple selector strategies
                selectors = [
                    f"#{element['id_attr']}",  # By ID
                    f"[id='{element['id_attr']}']",  # By ID attribute
                    f"button[id='{element['id_attr']}']",  # Button with ID
                    f"*[id='{element['id_attr']}']",  # Any element with ID
                ]

                for selector in selectors:
                    try:
                        # Try to find and click the element directly
                        print(f"🔍 Trying selector: {selector}")
                        await self.page.wait_for_selector(selector, timeout=2000)
                        await self.page.click(selector)
                        print(
                            f"👆 Clicked on element using direct selector: {selector}"
                        )

                        # Store the last action for reference
                        self.last_action = current_action
                        return True
                    except Exception as e:
                        print(f"⚠️ Failed to click with selector {selector}: {e}")
                        continue

                # If we get here, none of the selectors worked
                print(
                    f"❌ All direct selector attempts failed for element ID: {element['id_attr']}"
                )

                # Try a more aggressive approach - look for cookie consent buttons by text
                try:
                    cookie_selectors = [
                        "button:has-text('Accept')",
                        "button:has-text('Accept All')",
                        "button:has-text('Agree')",
                        "button:has-text('I Agree')",
                        "button:has-text('Allow')",
                        "button:has-text('Allow All')",
                        "button:has-text('Continue')",
                        "button:has-text('OK')",
                        "button:has-text('Got it')",
                        "button:has-text('Az összes elfogadása')",  # Hungarian "Accept all"
                        "[role='button']:has-text('Accept')",
                        "[role='button']:has-text('Accept All')",
                        "[role='button']:has-text('Agree')",
                        "[role='button']:has-text('I Agree')",
                        "[role='button']:has-text('Allow')",
                        "[role='button']:has-text('Allow All')",
                        "[role='button']:has-text('Continue')",
                        "[role='button']:has-text('OK')",
                        "[role='button']:has-text('Got it')",
                        "[role='button']:has-text('Az összes elfogadása')",  # Hungarian "Accept all"
                    ]

                    for selector in cookie_selectors:
                        try:
                            print(f"🍪 Trying cookie consent selector: {selector}")
                            await self.page.wait_for_selector(selector, timeout=1000)
                            await self.page.click(selector)
                            print(
                                f"👆 Clicked on cookie consent button using selector: {selector}"
                            )

                            # Store the last action for reference
                            self.last_action = {
                                "element_id": "cookie_consent",
                                "action": "click",
                            }
                            return True
                        except Exception:
                            continue
                except Exception as e:
                    print(f"❌ Cookie consent button selection failed: {e}")

            if not element:
                # If element not found, try to find a submit button if we're likely in a search context
                if (
                    "search" in decision.get("element_description", "").lower()
                    or "search" in decision.get("input_text", "").lower()
                ):
                    submit_button = self._find_submit_button(elements)
                    if submit_button:
                        print(
                            f"🔍 Element not found, but found a submit button that might help"
                        )
                        x = submit_button["x"] + submit_button["width"] / 2
                        y = submit_button["y"] + submit_button["height"] / 2

                        # Use human-like mouse movement
                        await self.human_like_mouse_movement(x, y)
                        await self.page.mouse.click(x, y)

                        self.last_action = {
                            "element_id": submit_button["id"],
                            "action": "click",
                        }
                        return True
                    else:
                        # Try pressing Enter as a last resort for search
                        print("🔍 No submit button found, pressing Enter as fallback")
                        await self.page.keyboard.press("Enter")
                        self.last_action = {"element_id": None, "action": "press_enter"}
                        return True

                # Try a last resort approach for cookie consent buttons
                try:
                    print("🍪 Attempting last resort cookie consent button detection")
                    cookie_button = await self.page.evaluate(
                        """() => {
                        // Common cookie consent button text patterns
                        const patterns = ['accept', 'agree', 'allow', 'consent', 'cookie', 'gdpr', 'az összes elfogadása'];
                        
                        // Find all buttons and links
                        const elements = [...document.querySelectorAll('button, [role="button"], a')];
                        
                        // Find the first element that matches our patterns
                        const cookieButton = elements.find(el => {
                            const text = (el.textContent || '').toLowerCase();
                            return patterns.some(pattern => text.includes(pattern));
                        });
                        
                        // If found, click it
                        if (cookieButton) {
                            cookieButton.click();
                            return true;
                        }
                        
                        return false;
                    }"""
                    )

                    if cookie_button:
                        print("👆 Clicked on cookie consent button using JavaScript")
                        self.last_action = {
                            "element_id": "cookie_consent_js",
                            "action": "click",
                        }
                        return True

                except Exception as e:
                    print(f"❌ Last resort cookie button detection failed: {e}")

                print(
                    f"⚠️ Element with ID {element_id} not found after trying fallback strategies"
                )
                return False

            # Get a descriptive name for the element
            element_desc = self._get_element_description(element)

            # Occasionally perform a human-like scroll before interacting with elements
            if random.random() < 0.3:  # 30% chance to scroll
                await self.human_like_scroll()

            # Execute the action
            if action == "click":
                # Click in the center of the element
                x = element["x"] + element["width"] / 2
                y = element["y"] + element["height"] / 2

                # Use human-like mouse movement
                await self.human_like_mouse_movement(x, y)

                # Add a small random delay before clicking
                await asyncio.sleep(random.uniform(0.1, 0.5))

                await self.page.mouse.click(x, y)
                print(f"👆 Clicked on element #{element['id']}: {element_desc}")

                # If this is a search input and we're clicking it again, also press Enter
                if (
                    self._is_search_element(element)
                    and hasattr(self, "last_action")
                    and self.last_action
                ):
                    if self.last_action.get("element_id") == element["id"]:
                        print("🔍 Clicking search element again, also pressing Enter")
                        await asyncio.sleep(
                            random.uniform(0.2, 0.7)
                        )  # Random delay before pressing Enter
                        await self.page.keyboard.press("Enter")

            elif action == "type":
                input_text = decision.get("input_text", "")
                # Check if this is a sensitive field
                is_sensitive = self._is_sensitive_field(element)

                # Click the element first with human-like movement
                x = element["x"] + element["width"] / 2
                y = element["y"] + element["height"] / 2
                await self.human_like_mouse_movement(x, y)
                await self.page.mouse.click(x, y)

                # Clear any existing text
                await self.page.keyboard.press("Control+A")
                await asyncio.sleep(random.uniform(0.1, 0.3))  # Small random delay
                await self.page.keyboard.press("Backspace")
                await asyncio.sleep(random.uniform(0.2, 0.5))  # Small random delay

                # Type the text with human-like typing speed
                for char in input_text:
                    await self.page.keyboard.type(char)
                    # Random typing delay between characters
                    await asyncio.sleep(random.uniform(0.05, 0.15))

                # Print with masked value if sensitive
                if is_sensitive:
                    print(
                        f"⌨️ Typed [REDACTED] into element #{element['id']}: {element_desc}"
                    )
                else:
                    print(
                        f"⌨️ Typed '{input_text}' into element #{element['id']}: {element_desc}"
                    )

                # If this is a search input, automatically press Enter after typing
                if self._is_search_element(element):
                    print("🔍 Search input detected, pressing Enter after typing")
                    await asyncio.sleep(
                        random.uniform(0.3, 0.8)
                    )  # Random delay before pressing Enter
                    await self.page.keyboard.press("Enter")

            # Store the last action for reference
            self.last_action = current_action
            return True

        except Exception as e:
            print(f"❌ Error executing decision: {e}")
            traceback.print_exc()
            return False

    def _is_search_element(self, element):
        """Check if an element is likely a search input"""
        return (
            element["type"] == "search"
            or "search" in (element["id_attr"] or "").lower()
            or "search" in (element["name"] or "").lower()
            or "search" in (element["placeholder"] or "").lower()
            or "search" in (element["aria_label"] or "").lower()
            or element["aria_role"] == "search"
            or element["aria_role"] == "searchbox"
        )

    def _find_submit_button(self, elements):
        """Find a submit button that might be associated with a form/search"""
        # Look for submit buttons
        submit_button = next(
            (
                e
                for e in elements
                if (
                    e["type"] == "submit"
                    or (e["tag"] == "button" and e["type"] == "submit")
                    or (e["tag"] == "input" and e["type"] == "submit")
                )
            ),
            None,
        )

        if submit_button:
            return submit_button

        # Look for buttons with search-related attributes
        search_button = next(
            (
                e
                for e in elements
                if (
                    (
                        e["tag"] == "button"
                        or "button" in e["class_attr"].lower()
                        or e["aria_role"] == "button"
                    )
                    and (
                        "search" in (e["id_attr"] or "").lower()
                        or "search" in (e["name"] or "").lower()
                        or "search" in (e["text"] or "").lower()
                        or "search" in (e["aria_label"] or "").lower()
                    )
                )
            ),
            None,
        )

        if search_button:
            return search_button

        # Look for elements with magnifying glass icon or search icon classes
        icon_button = next(
            (
                e
                for e in elements
                if (
                    "search-icon" in (e["class_attr"] or "").lower()
                    or "searchicon" in (e["class_attr"] or "").lower()
                    or "icon-search" in (e["class_attr"] or "").lower()
                    or "fa-search" in (e["class_attr"] or "").lower()
                    or "material-icons" in (e["class_attr"] or "").lower()
                    and "search" in (e["text"] or "").lower()
                )
            ),
            None,
        )

        return icon_button

    def _find_element_with_fallback(self, element_id, decision, elements):
        """
        Find an element using multiple fallback strategies:
        1. Try exact ID match first
        2. Try matching by element attributes (placeholder, name, etc.)
        3. Try matching by element text content
        4. Try matching by element description/type
        """
        # Strategy 1: Exact ID match (original approach)
        element = next((e for e in elements if e["id"] == element_id), None)
        if element:
            print(f"✅ Found element by exact ID: {element_id}")
            return element

        # Get additional context from the decision
        target_text = decision.get("input_text", "")
        element_description = decision.get("element_description", "").lower()
        action = decision.get("action", "click")

        # Special handling for input fields when the action is "type"
        if action == "type":
            # First, try to find an exact match based on the element description
            input_element = self._find_input_by_description(
                elements, element_description
            )
            if input_element:
                return input_element

            # Then try to find by common input field attributes
            input_element = self._find_input_by_attributes(
                elements, element_description, target_text
            )
            if input_element:
                return input_element

        # Strategy 2: Match by HTML ID attribute
        if isinstance(element_id, str) and (
            element_id.startswith("#")
            or element_id.startswith("L")
            or element_id.startswith("gb")
        ):
            # Handle cases where the AI provides a CSS selector like "#search-input" or an element ID like "L2AGLb"
            html_id = element_id.lstrip("#")
            element = next((e for e in elements if e["id_attr"] == html_id), None)
            if element:
                print(f"✅ Found element by HTML ID attribute: {html_id}")
                return element

            # If not found by ID, we'll try to use a direct selector in execute_decision method
            print(
                f"⚠️ Element with ID {html_id} not found in element list, will try direct selector"
            )
            return {"id": element_id, "id_attr": html_id, "is_direct_selector": True}

        # Strategy 3: Match by text content
        if element_description and "cookie" in element_description:
            # Look for cookie consent buttons by text
            cookie_text_patterns = [
                "accept",
                "agree",
                "allow",
                "consent",
                "accept all",
                "i agree",
                "az összes elfogadása",
            ]
            for e in elements:
                if e.get("text") and any(
                    pattern in e["text"].lower() for pattern in cookie_text_patterns
                ):
                    print(f"✅ Found cookie consent button by text: {e['text']}")
                    return e

        # Strategy 4: Match by placeholder text
        if target_text or element_description:
            search_terms = [
                term.lower() for term in [target_text, element_description] if term
            ]

            # Look for elements with matching placeholder text
            for term in search_terms:
                for e in elements:
                    if e["placeholder"] and term in e["placeholder"].lower():
                        print(
                            f"✅ Found element by placeholder text containing: {term}"
                        )
                        return e

            # Strategy 5: Match by name attribute
            for term in search_terms:
                for e in elements:
                    if e["name"] and term in e["name"].lower():
                        print(f"✅ Found element by name attribute containing: {term}")
                        return e

            # Strategy 6: Match by visible text content
            for term in search_terms:
                for e in elements:
                    if e["text"] and term in e["text"].lower():
                        print(f"✅ Found element by text content containing: {term}")
                        return e

        # Strategy 7: Look for search-related elements
        if "search" in element_description or "search" in target_text.lower():
            # Look for search inputs
            search_element = next(
                (
                    e
                    for e in elements
                    if (
                        e["type"] == "search"
                        or "search" in (e["id_attr"] or "").lower()
                        or "search" in (e["name"] or "").lower()
                        or "search" in (e["placeholder"] or "").lower()
                    )
                ),
                None,
            )
            if search_element:
                print(f"✅ Found search element by search-related attributes")
                return search_element

        # Strategy 8: Type-based fallback for common elements
        if "type" in decision:
            element_type = decision["type"].lower()
            if element_type in ["text", "search", "email", "password"]:
                # Find the first input of that type
                input_element = next(
                    (
                        e
                        for e in elements
                        if e["tag"] == "input" and e["type"] == element_type
                    ),
                    None,
                )
                if input_element:
                    print(f"✅ Found element by input type: {element_type}")
                    return input_element

        # No matching element found after all fallback strategies
        return None

    def _find_input_by_description(self, elements, description):
        """Find an input element based on its description"""
        if not description:
            return None

        # Common input field descriptors
        input_descriptors = {
            "search": ["search", "find", "lookup", "query"],
            "email": ["email", "e-mail", "mail"],
            "password": ["password", "pwd", "pass"],
            "username": ["username", "user", "login"],
            "name": ["name", "full name", "first name", "last name"],
            "phone": ["phone", "mobile", "tel", "telephone"],
            "address": ["address", "location", "street"],
            "message": ["message", "comment", "feedback"],
        }

        # Check which type of input we're looking for
        input_type = None
        for type_name, descriptors in input_descriptors.items():
            if any(desc in description for desc in descriptors):
                input_type = type_name
                break

        if input_type:
            # First try exact type match
            element = next(
                (
                    e
                    for e in elements
                    if e["tag"] == "input" and e["type"] == input_type
                ),
                None,
            )
            if element:
                print(f"✅ Found input element by type: {input_type}")
                return element

            # Then try matching by role or purpose
            element = next(
                (
                    e
                    for e in elements
                    if (e["tag"] == "input" or e["tag"] == "textarea")
                    and any(
                        desc in (e["aria_label"] or "").lower()
                        or desc in (e["placeholder"] or "").lower()
                        or desc in (e["name"] or "").lower()
                        for desc in input_descriptors[input_type]
                    )
                ),
                None,
            )
            if element:
                print(f"✅ Found input element by purpose: {input_type}")
                return element

        return None

    def _find_input_by_attributes(self, elements, description, target_text):
        """Find an input element based on its attributes and context"""
        if not elements:
            return None

        # Score each input element based on how well it matches
        scored_elements = []
        for element in elements:
            if element["tag"] not in ["input", "textarea"]:
                continue

            score = 0
            attrs = {
                "placeholder": element.get("placeholder", "").lower(),
                "name": element.get("name", "").lower(),
                "id_attr": element.get("id_attr", "").lower(),
                "aria_label": element.get("aria_label", "").lower(),
                "type": element.get("type", "").lower(),
                "parent_text": element.get("parent_text", "").lower(),
            }

            # Check description match
            if description:
                for attr_value in attrs.values():
                    if description in attr_value:
                        score += 3
                    elif any(word in attr_value for word in description.split()):
                        score += 1

            # Check target text relevance
            if target_text:
                for attr_value in attrs.values():
                    if target_text.lower() in attr_value:
                        score += 2

            # Bonus points for proper input types
            if element["type"] in ["text", "search", "email", "password"]:
                score += 2

            # Bonus points for visible elements
            if element.get("is_likely_interactive", False):
                score += 1

            if score > 0:
                scored_elements.append((score, element))

        # Sort by score and return the best match
        if scored_elements:
            scored_elements.sort(reverse=True, key=lambda x: x[0])
            best_match = scored_elements[0][1]
            print(
                f"✅ Found best matching input element: {self._get_element_description(best_match)}"
            )
            return best_match

        return None

    def _get_element_description(self, element):
        """Get a descriptive name for an element"""
        if not element:
            return "[Unknown element]"

        # Try different properties in order of preference
        description_parts = []

        # Add element type information
        element_type = ""
        if element.get("tag"):
            element_type = element.get("tag")
            if element.get("type"):
                element_type += f" type={element.get('type')}"
            if element.get("aria_role"):
                element_type += f" role={element.get('aria_role')}"

        description_parts.append(f"[{element_type}]")

        # Add text content if available
        if element.get("text") and element["text"].strip():
            # Truncate long text
            text = element["text"].strip()
            if len(text) > 50:
                text = text[:47] + "..."
            description_parts.append(f'"{text}"')

        # Add placeholder if available and no text
        elif element.get("placeholder") and element["placeholder"].strip():
            description_parts.append(f'[Placeholder: "{element["placeholder"]}"]')

        # Add aria-label if available and no text or placeholder
        elif element.get("aria_label") and element["aria_label"].strip():
            description_parts.append(f'[Aria-label: "{element["aria_label"]}"]')

        # Add title if available and no text, placeholder, or aria-label
        elif element.get("title") and element["title"].strip():
            description_parts.append(f'[Title: "{element["title"]}"]')

        # Add name if available and no other descriptive text
        elif element.get("name") and element["name"].strip():
            description_parts.append(f'[Name: "{element["name"]}"]')

        # Add ID if available and no other descriptive text
        elif element.get("id_attr") and element["id_attr"].strip():
            description_parts.append(f'[ID: "{element["id_attr"]}"]')

        # Add class information if it might be helpful
        if element.get("class_attr") and element["class_attr"].strip():
            class_attr = element["class_attr"]
            # Only include class if it's short enough to be meaningful
            if len(class_attr) < 50:
                description_parts.append(f'[Class: "{class_attr}"]')

        # Check if this might be a cookie-related element
        if (
            element.get("text")
            or element.get("aria_label")
            or element.get("title")
            or element.get("parent_text")
        ):
            text = (
                element.get("text", "")
                + " "
                + element.get("aria_label", "")
                + " "
                + element.get("title", "")
                + " "
                + element.get("parent_text", "")
            ).lower()

            cookie_terms = [
                "cookie",
                "consent",
                "accept",
                "agree",
                "allow",
                "privacy",
                "gdpr",
                "ccpa",
            ]
            if any(term in text for term in cookie_terms):
                description_parts.append("[Possible cookie consent element]")

        # Join all parts
        return " ".join(description_parts)

    def _is_sensitive_field(self, element):
        """Check if an element is likely to contain sensitive information"""
        # Check element type
        if element.get("type") in ["password", "key"]:
            return True

        # Check element name, id, or placeholder
        sensitive_keywords = [
            "password",
            "pwd",
            "secret",
            "token",
            "key",
            "api",
            "auth",
            "credential",
        ]

        for keyword in sensitive_keywords:
            for attr in ["name", "id_attr", "placeholder"]:
                if element.get(attr) and keyword.lower() in element.get(attr).lower():
                    return True

        return False

    async def check_goal_completion(self, screenshot_path, goal, url):
        """
        Explicitly check if the goal has been achieved by asking the AI
        This uses the same conversation history for context
        """
        # Prepare system message focused on goal detection
        system_message = """You are an AI web navigator that helps users accomplish tasks on websites.
Your job is to analyze the current webpage and determine if the user's goal has been achieved.

IMPORTANT CONSIDERATIONS:
1. Look for clear indicators that the goal has been completed
2. Consider the current state of the webpage in relation to the goal
3. Use your knowledge of typical web flows and user journeys
4. Consider the history of actions taken so far
5. Be conservative - only report goal completion when you're confident

Respond in JSON format with these fields:
- goal_achieved: true/false whether the goal has been completed
- confidence: 0.0-1.0 indicating your confidence that the goal is achieved
- reasoning: Detailed explanation of why you believe the goal has or hasn't been achieved
"""

        # Prepare user message for goal detection
        user_message = f"""
Current URL: {url}
Step: {self.step_count}
Goal: {goal}

Please analyze the screenshot and determine if the goal has been achieved.
Consider all the previous steps and actions taken so far.
"""

        # Add the conversation history to provide context
        messages = [
            {"role": "system", "content": system_message},
        ]

        # Add conversation history (last 6 exchanges)
        for msg in self.conversation_history[-12:]:
            messages.append(msg)

        # Add the current user message
        messages.append(
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": user_message},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{self._encode_image(screenshot_path)}"
                        },
                    },
                ],
            }
        )

        # Make the API call
        response = await self.client.chat.completions.create(
            model=os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME", "gpt-4o"),
            messages=messages,
            response_format={"type": "json_object"},
            max_tokens=1000,
        )

        # Parse the response
        response_content = response.choices[0].message.content

        # Store the exchange in conversation history
        self.conversation_history.append({"role": "user", "content": user_message})
        self.conversation_history.append(
            {"role": "assistant", "content": response_content}
        )

        try:
            result = json.loads(response_content)
            goal_achieved = result.get("goal_achieved", False)
            confidence = result.get("confidence", 0.0)
            reasoning = result.get("reasoning", "No reasoning provided")

            print(
                f"🎯 Goal detection: {'Achieved' if goal_achieved else 'Not achieved'} (confidence: {confidence})"
            )
            print(f"💭 Reasoning: {reasoning}")

            # Update goal achieved status if confidence is high enough
            if goal_achieved and confidence >= self.goal_confidence:
                self.goal_achieved = True
                print(f"🏆 Goal achieved with confidence {confidence}!")

            return goal_achieved, confidence, reasoning

        except json.JSONDecodeError:
            print("⚠️ Failed to parse AI goal detection response as JSON")
            return False, 0.0, "Failed to parse response"

    async def detect_captcha(self):
        """Detect if a captcha is present on the page"""
        try:
            # Common captcha identifiers
            captcha_selectors = [
                "iframe[src*='recaptcha']",
                "iframe[src*='captcha']",
                "iframe[title*='recaptcha']",
                "iframe[title*='captcha']",
                "div.g-recaptcha",
                "div[class*='captcha']",
                "div[id*='captcha']",
                "input[name*='captcha']",
                "img[alt*='captcha']",
                "div[aria-label*='captcha']",
                "div[data-sitekey]",  # reCAPTCHA v2/v3
                "div.h-captcha",  # hCaptcha
                "div[class*='turnstile']",  # Cloudflare Turnstile
            ]

            # Check for captcha elements
            for selector in captcha_selectors:
                captcha_element = await self.page.query_selector(selector)
                if captcha_element:
                    return True, selector

            # Check for common captcha text
            page_text = await self.page.evaluate("() => document.body.innerText")
            captcha_keywords = [
                "captcha",
                "recaptcha",
                "i'm not a robot",
                "verify you are human",
                "security check",
                "prove you're human",
                "bot check",
                "verification challenge",
            ]

            for keyword in captcha_keywords:
                if keyword.lower() in page_text.lower():
                    return True, f"Text containing '{keyword}'"

            return False, None
        except Exception as e:
            print(f"⚠️ Error detecting captcha: {e}")
            return False, None

    async def disable_automation_for_manual_browsing(self):
        """Completely disable automation features for manual browsing"""
        try:
            # Execute JavaScript to remove all automation indicators
            await self.page.evaluate(
                """() => {
                // Override all automation-related properties
                const originalNavigator = window.navigator;
                
                // Create a comprehensive set of overrides
                const overrides = {
                    webdriver: false,
                    userAgent: navigator.userAgent.replace(/HeadlessChrome/gi, 'Chrome'),
                    plugins: { length: 5 },
                    languages: ['en-US', 'en'],
                    platform: 'MacIntel',
                    hardwareConcurrency: 8,
                    deviceMemory: 8,
                    maxTouchPoints: 0,
                    doNotTrack: null,
                };
                
                // Apply overrides to navigator
                Object.defineProperties(
                    navigator,
                    Object.entries(overrides).reduce((result, [key, value]) => {
                        result[key] = {
                            get: () => value,
                            configurable: true
                        };
                        return result;
                    }, {})
                );
                
                // Create fake plugins
                if (Object.defineProperty) {
                    const fakePlugins = [
                        { name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
                        { name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai', description: 'Portable Document Format' },
                        { name: 'Native Client', filename: 'internal-nacl-plugin', description: '' }
                    ];
                    
                    // Create a plugins array with the correct properties
                    const plugins = [];
                    for (let i = 0; i < fakePlugins.length; i++) {
                        plugins[i] = fakePlugins[i];
                    }
                    plugins.length = fakePlugins.length;
                    
                    Object.defineProperty(navigator, 'plugins', {
                        get: () => plugins,
                        enumerable: true,
                        configurable: true
                    });
                }
                
                // Clean up automation flags
                delete window.__webdriver_script_fn;
                delete window.__driver_evaluate;
                delete window.__webdriver_evaluate;
                delete window.__selenium_evaluate;
                delete window.__selenium_unwrapped;
                delete window.cdc_adoQpoasnfa76pfcZLmcfl_Array;
                delete window.cdc_adoQpoasnfa76pfcZLmcfl_Promise;
                delete window.cdc_adoQpoasnfa76pfcZLmcfl_Symbol;
                
                // Override permissions API
                if (navigator.permissions) {
                    const originalQuery = navigator.permissions.query;
                    navigator.permissions.query = function(parameters) {
                        if (parameters.name === 'notifications' || 
                            parameters.name === 'geolocation' || 
                            parameters.name === 'midi' || 
                            parameters.name === 'camera' || 
                            parameters.name === 'microphone') {
                            return Promise.resolve({ state: 'prompt', onchange: null });
                        }
                        return originalQuery.call(this, parameters);
                    };
                }
                
                // Override WebGL fingerprinting
                const getParameterProxies = {};
                if (window.WebGLRenderingContext) {
                    const originalGetParameter = WebGLRenderingContext.prototype.getParameter;
                    WebGLRenderingContext.prototype.getParameter = function(parameter) {
                        // UNMASKED_VENDOR_WEBGL and UNMASKED_RENDERER_WEBGL are commonly used for fingerprinting
                        if (parameter === 37445) { // UNMASKED_VENDOR_WEBGL
                            return 'Intel Inc.';
                        }
                        if (parameter === 37446) { // UNMASKED_RENDERER_WEBGL
                            return 'Intel Iris OpenGL Engine';
                        }
                        return originalGetParameter.call(this, parameter);
                    };
                }
                
                // Override canvas fingerprinting more aggressively
                const originalToDataURL = HTMLCanvasElement.prototype.toDataURL;
                HTMLCanvasElement.prototype.toDataURL = function(type) {
                    // Add subtle noise to any canvas data URL
                    const dataURL = originalToDataURL.apply(this, arguments);
                    if (this.width > 16 && this.height > 16) {
                        // Only modify if it's likely being used for fingerprinting
                        // (very small canvases are often used for UI elements)
                        return dataURL; // Return unmodified for now to avoid breaking functionality
                    }
                    return dataURL;
                };
                
                // Override timing functions to prevent timing attacks
                const originalPerformance = window.performance;
                const originalNow = window.performance.now;
                const originalGetEntries = window.performance.getEntries;
                
                window.performance.now = function() {
                    const result = originalNow.call(originalPerformance);
                    // Add small random noise to timing
                    return result + Math.random() * 0.01;
                };
                
                // Modify chrome object if it exists
                if (window.chrome) {
                    // Create a fake chrome.runtime object if it doesn't exist
                    if (!window.chrome.runtime) {
                        window.chrome.runtime = {};
                    }
                    
                    // Add a fake sendMessage function
                    window.chrome.runtime.sendMessage = function() {
                        return Promise.resolve();
                    };
                }
                
                // Add a fake notification API
                if (!window.Notification) {
                    window.Notification = {
                        permission: 'default',
                        requestPermission: function() {
                            return Promise.resolve('default');
                        }
                    };
                }
                
                console.log('Automation detection protections applied for manual browsing');
            }"""
            )

            # Add a cookie to make the browser appear more like a regular user
            try:
                domain = self.page.url.split("/")[2]
                await self.context.add_cookies(
                    [
                        {
                            "name": "user_session",
                            "value": f"session_{random.randint(10000, 99999)}",
                            "domain": domain,
                            "path": "/",
                            "expires": int(time.time()) + 86400,
                            "httpOnly": True,
                            "secure": True,
                            "sameSite": "Lax",
                        }
                    ]
                )
            except Exception as cookie_error:
                print(f"⚠️ Could not set cookie: {cookie_error}")

            print("🔓 Disabled automation detection for manual browsing")
            return True
        except Exception as e:
            print(f"⚠️ Error disabling automation for manual browsing: {e}")
            return False

    async def handle_captcha(self):
        """Handle detected captcha with manual intervention"""
        print(
            "\n🔒 CAPTCHA detected! Taking screenshot and waiting for manual intervention"
        )

        # Take a screenshot of the captcha
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        captcha_screenshot_path = self.output_dir / f"captcha_{timestamp}.png"
        await self.page.screenshot(path=captcha_screenshot_path)

        print(f"📸 Captcha screenshot saved to {captcha_screenshot_path}")
        print("⚠️ Manual intervention required to solve the captcha")

        # Completely disable automation for manual browsing
        await self.disable_automation_for_manual_browsing()

        # Wait for user to manually solve the captcha and confirm
        print("\n📢 Please manually solve the captcha in the browser window.")
        print("⌨️  After solving, press Enter in this terminal to continue...")
        print("💡 TIP: If you encounter multiple captchas, try to:")
        print("   1. Complete the entire verification process")
        print("   2. Navigate to the main site manually if needed")
        print("   3. Only press Enter when you're on a non-captcha page")

        # Create a simple input mechanism to wait for user confirmation
        user_input = input("Press Enter after solving the captcha...")

        # Add a small delay after user confirmation
        await asyncio.sleep(2)

        # Verify if we're still on a captcha page
        captcha_still_detected, captcha_info = await self.detect_captcha()
        if captcha_still_detected:
            print(f"⚠️ Captcha still detected: {captcha_info}")
            print(
                "🔄 You may need to solve it again or the site might be using multiple layers of verification"
            )

            # Ask user if they want to try again or continue anyway
            retry = input("Try solving again? (y/n): ").lower().strip() == "y"
            if retry:
                return await self.handle_captcha()
            else:
                print("⚠️ Continuing despite captcha still being detected")
        else:
            print("✅ Captcha appears to be solved successfully!")

        # Re-apply stealth mode
        stealth_sync(self.page)
        print("🛡️ Re-applied stealth mode to page")

        # Add some human-like behavior after solving captcha
        await self.human_like_scroll()

        print("▶️ Resuming test after captcha intervention")
        return True

    async def add_browser_fingerprint_protection(self):
        """Add additional browser fingerprint protection"""
        try:
            # Execute JavaScript to modify browser fingerprinting surfaces
            await self.page.evaluate(
                """() => {
                // Function to generate consistent but random values
                const generateConsistentRandom = (seed, min, max) => {
                    const x = Math.sin(seed) * 10000;
                    const rand = x - Math.floor(x);
                    return Math.floor(rand * (max - min + 1)) + min;
                };
                
                // Create a seed based on user agent
                const seed = navigator.userAgent.split('').reduce((acc, char) => acc + char.charCodeAt(0), 0);
                
                // Override canvas fingerprinting
                const originalGetContext = HTMLCanvasElement.prototype.getContext;
                HTMLCanvasElement.prototype.getContext = function(type, attributes) {
                    const context = originalGetContext.call(this, type, attributes);
                    if (context && type.includes('2d')) {
                        const originalFillText = context.fillText;
                        context.fillText = function(...args) {
                            originalFillText.apply(this, args);
                            // Add subtle noise to the canvas
                            const imageData = context.getImageData(0, 0, this.canvas.width, this.canvas.height);
                            const pixels = imageData.data;
                            for (let i = 0; i < pixels.length; i += 4) {
                                // Only modify some pixels slightly
                                if (Math.random() < 0.1) {
                                    pixels[i] = Math.max(0, Math.min(255, pixels[i] + generateConsistentRandom(seed + i, -2, 2)));
                                    pixels[i+1] = Math.max(0, Math.min(255, pixels[i+1] + generateConsistentRandom(seed + i + 1, -2, 2)));
                                    pixels[i+2] = Math.max(0, Math.min(255, pixels[i+2] + generateConsistentRandom(seed + i + 2, -2, 2)));
                                }
                            }
                            context.putImageData(imageData, 0, 0);
                        };
                    }
                    return context;
                };
                
                // Override audio fingerprinting
                if (window.AudioContext || window.webkitAudioContext) {
                    const AudioContextClass = window.AudioContext || window.webkitAudioContext;
                    const originalGetChannelData = AudioBuffer.prototype.getChannelData;
                    
                    AudioBuffer.prototype.getChannelData = function(channel) {
                        const data = originalGetChannelData.call(this, channel);
                        // Only modify data if it's likely being used for fingerprinting
                        // (small buffers are often used for fingerprinting)
                        if (this.length < 1000) {
                            const noise = 0.0001; // Very small noise
                            for (let i = 0; i < data.length; i++) {
                                if (Math.random() < 0.1) {
                                    data[i] += generateConsistentRandom(seed + i, -noise, noise);
                                }
                            }
                        }
                        return data;
                    };
                }
                
                // Override font fingerprinting
                const originalMeasureText = CanvasRenderingContext2D.prototype.measureText;
                CanvasRenderingContext2D.prototype.measureText = function(text) {
                    const result = originalMeasureText.call(this, text);
                    // Add tiny random variations to text metrics
                    const noise = 0.01;
                    if (result.width) {
                        Object.defineProperty(result, 'width', {
                            get: function() {
                                return originalMeasureText.call(this, text).width + 
                                    generateConsistentRandom(seed + text.length, -noise, noise);
                            }
                        });
                    }
                    return result;
                };
            }"""
            )

            print("🛡️ Applied additional browser fingerprint protection")
            return True
        except Exception as e:
            print(f"⚠️ Error applying additional fingerprint protection: {e}")
            return False

    async def run_test(self, url, goal, max_steps=10):
        """Run a test with the given URL and goal"""
        try:
            print(f"🌐 Starting test with URL: {url}")
            print(f"🎯 Goal: {goal}")

            # Reset state
            self.step_count = 0
            self.goal_achieved = False
            self.conversation_history = []
            self.last_action = None  # Initialize last_action tracking

            # Navigate directly to the target URL
            print("🔄 Navigating to the URL...")
            await self.page.goto(url)

            # Main test loop
            while self.step_count < max_steps and not self.goal_achieved:
                self.step_count += 1
                print(f"\n📍 Step {self.step_count}/{max_steps}")

                # Wait for the page to fully load
                await self.wait_for_page_load()

                # Add some random mouse movements occasionally
                if random.random() < 0.3:
                    # Move mouse to a random position on the page
                    viewport_size = await self.page.evaluate(
                        """() => {
                        return {
                            width: window.innerWidth,
                            height: window.innerHeight
                        }
                    }"""
                    )

                    random_x = random.randint(100, viewport_size["width"] - 200)
                    random_y = random.randint(100, viewport_size["height"] - 200)
                    await self.human_like_mouse_movement(random_x, random_y)

                # Check for captcha
                captcha_detected, captcha_info = await self.detect_captcha()
                if captcha_detected:
                    print(f"🔒 Captcha detected: {captcha_info}")
                    await self.handle_captcha()

                    # After handling captcha, check if we need to reload the page
                    current_url = self.page.url
                    if (
                        "captcha" in current_url.lower()
                        or "challenge" in current_url.lower()
                    ):
                        print(
                            "🔄 Still on captcha/challenge page, attempting to navigate to original URL"
                        )
                        await self.page.goto(url)
                        await self.wait_for_page_load()

                # Take a screenshot for goal completion check
                screenshot_path = await self.take_screenshot()

                # Check goal completion first at each step
                goal_achieved, confidence, reasoning = await self.check_goal_completion(
                    screenshot_path, goal, self.page.url
                )

                # If goal is achieved with sufficient confidence, exit the loop
                if goal_achieved and confidence >= self.goal_confidence:
                    print(
                        f"🎉 Goal achieved with confidence {confidence:.2f} (threshold: {self.goal_confidence:.2f})"
                    )
                    print(f"💭 Reasoning: {reasoning}")
                    self.goal_achieved = True
                    break

                # If goal is not achieved, continue with the next action
                print(
                    f"⚠️ Goal verification: Not achieved (confidence: {confidence:.2f})"
                )

                # Gather all elements from the page
                elements = await self.gather_page_elements()

                # Ask AI for a decision
                decision = await self.ask_ai_for_decision(
                    screenshot_path, elements, goal, self.page.url
                )

                # Execute the decision
                success = await self.execute_decision(decision, elements)

                # Wait a bit before the next action to allow page to update
                await asyncio.sleep(1)

            # Final result
            if self.goal_achieved:
                print(f"✅ Test completed successfully in {self.step_count} steps")
                result = True
            else:
                print(f"❌ Test failed to achieve the goal in {max_steps} steps")
                result = False

            # Close the browser
            await self.stop()

            # Exit the program
            print("👋 Exiting program...")
            import sys

            sys.exit(0)

            return result

        except Exception as e:
            print(f"❌ Error during test: {e}")
            traceback.print_exc()

            # Close the browser even if there was an error
            try:
                await self.stop()
            except:
                pass

            # Exit the program
            print("👋 Exiting program due to error...")
            import sys

            sys.exit(1)

            return False

    def _encode_image(self, image_path):
        """Encode image to base64 for API request"""
        import base64

        with open(image_path, "rb") as image_file:
            return base64.b64encode(image_file.read()).decode("utf-8")

    async def human_like_scroll(self):
        """Perform human-like scrolling on the page"""
        try:
            # Get page height
            page_height = await self.page.evaluate("() => document.body.scrollHeight")
            viewport_height = await self.page.evaluate("() => window.innerHeight")

            # Calculate a random number of scroll steps
            scroll_steps = random.randint(3, 8)

            # Perform scrolling in steps with random pauses
            current_position = 0
            for i in range(scroll_steps):
                # Calculate next position with some randomness
                step_size = random.randint(
                    int(viewport_height * 0.5), int(viewport_height * 0.9)
                )

                # Make sure we don't scroll past the page
                next_position = min(
                    current_position + step_size, page_height - viewport_height
                )

                # Scroll to the position
                await self.page.evaluate(f"window.scrollTo(0, {next_position})")

                # Update current position
                current_position = next_position

                # Random pause between scrolls
                await asyncio.sleep(random.uniform(0.3, 1.2))

            # Scroll back up a bit to simulate reading
            if random.random() < 0.7:  # 70% chance to scroll back up
                scroll_up = random.randint(
                    int(viewport_height * 0.2), int(viewport_height * 0.5)
                )
                await self.page.evaluate(
                    f"window.scrollTo(0, {max(0, current_position - scroll_up)})"
                )
                await asyncio.sleep(random.uniform(0.5, 1.5))

        except Exception as e:
            print(f"⚠️ Error during human-like scrolling: {e}")

    async def human_like_mouse_movement(self, target_x, target_y):
        """Move the mouse in a human-like way to the target coordinates"""
        try:
            # Get current mouse position
            current_position = await self.page.evaluate(
                "() => ({ x: window.mouseX || 0, y: window.mouseY || 0 })"
            )

            start_x = current_position.get("x", 0)
            start_y = current_position.get("y", 0)

            # Calculate distance
            distance = ((target_x - start_x) ** 2 + (target_y - start_y) ** 2) ** 0.5

            # Determine number of steps based on distance
            steps = min(max(int(distance / 50), 5), 15)

            # Generate control points for a bezier curve to make movement more natural
            control_x = start_x + (target_x - start_x) * random.uniform(0.3, 0.7)
            control_y = start_y + (target_y - start_y) * random.uniform(0.3, 0.7)

            # Add some randomness to control point
            control_x += random.uniform(-100, 100)
            control_y += random.uniform(-100, 100)

            # Move mouse along the curve
            for i in range(steps + 1):
                t = i / steps
                # Quadratic bezier formula
                x = int(
                    (1 - t) ** 2 * start_x
                    + 2 * (1 - t) * t * control_x
                    + t**2 * target_x
                )
                y = int(
                    (1 - t) ** 2 * start_y
                    + 2 * (1 - t) * t * control_y
                    + t**2 * target_y
                )

                await self.page.mouse.move(x, y)

                # Random delay between movements
                await asyncio.sleep(random.uniform(0.01, 0.05))

        except Exception as e:
            print(f"⚠️ Error during human-like mouse movement: {e}")
            # Fallback to direct movement
            await self.page.mouse.move(target_x, target_y)
