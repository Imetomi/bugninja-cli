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

import dotenv
from playwright.async_api import async_playwright, Page, Browser, BrowserContext
from openai import AsyncAzureOpenAI


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

        # Launch browser
        self.browser = await playwright.chromium.launch(headless=self.headless)

        # Create browser context with video recording
        video_size = self.video_settings.get(
            self.video_quality, self.video_settings["medium"]
        )
        self.context = await self.browser.new_context(
            record_video_dir=str(self.output_dir), record_video_size=video_size
        )

        # Set up event listeners for new pages and page closures
        self.context.on("page", self._handle_new_page)

        # Create a new page
        self.page = await self.context.new_page()
        self.pages.append(self.page)

        # Set up page-specific event handlers
        await self._setup_page_event_handlers(self.page)

        print("🚀 Browser started with video recording")

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
        # Get all clickable elements
        elements = await self.page.evaluate(
            """() => {
            const getVisibleElements = () => {
                // Get all potentially interactive elements
                const selectors = [
                    'a', 'button', 'input', 'select', 'textarea',
                    '[role="button"]', '[role="link"]', '[role="checkbox"]',
                    '[role="radio"]', '[role="tab"]', '[role="menuitem"]',
                    '[onclick]', '[class*="btn"]', '[class*="button"]'
                ];
                
                const elements = Array.from(document.querySelectorAll(selectors.join(',')));
                
                // Filter for visible elements
                return elements
                    .filter(el => {
                        const rect = el.getBoundingClientRect();
                        return (
                            rect.width > 0 &&
                            rect.height > 0 &&
                            window.getComputedStyle(el).display !== 'none' &&
                            window.getComputedStyle(el).visibility !== 'hidden'
                        );
                    })
                    .map((el, index) => {
                        const rect = el.getBoundingClientRect();
                        return {
                            id: index,
                            tag: el.tagName.toLowerCase(),
                            type: el.getAttribute('type') || '',
                            text: el.innerText || el.textContent || '',
                            placeholder: el.getAttribute('placeholder') || '',
                            value: el.value || '',
                            name: el.getAttribute('name') || '',
                            id_attr: el.getAttribute('id') || '',
                            class_attr: el.getAttribute('class') || '',
                            href: el.getAttribute('href') || '',
                            x: rect.x,
                            y: rect.y,
                            width: rect.width,
                            height: rect.height,
                            is_visible: true
                        };
                    });
            };
            
            return getVisibleElements();
        }"""
        )

        print(f"🔍 Found {len(elements)} interactive elements")
        return elements

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
1. ALWAYS handle cookie banners and privacy prompts first before anything else
2. If you are provided with a login form, use the provided credentials when appropriate, this could be also part of a testing journey on many websites. In some cases you maybe have register a new account. You can use made-up information with John Doe to fill up the form.
3. Focus on the main task after handling popups and logins
4. Try to examine multiple options if the first try didn't work in a previous step for a specific task.
5. Evaluate if the goal has been achieved after each step

For each step, you will:
1. Analyze the screenshot of the current webpage
2. Choose ONE element to interact with (click or type)
3. Specify exactly what to do with that element
4. Explain your reasoning
5. Indicate if you believe the goal has been achieved

Respond in JSON format with these fields:
- action: "click" or "type"
- element_id: ID of the element to interact with
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

        user_message += """
Please analyze the screenshot and choose the next action to take.
"""

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
                        "image_url": {
                            "url": f"data:image/png;base64,{self._encode_image(screenshot_path)}"
                        },
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
                    f"🎯 Goal achieved with confidence {decision.get('confidence', 0)}"
                )

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

            # Find the element in the list
            element = next((e for e in elements if e["id"] == element_id), None)

            if not element:
                print(f"⚠️ Element with ID {element_id} not found")
                return False

            # Get a descriptive name for the element
            element_desc = self._get_element_description(element)

            # Execute the action
            if action == "click":
                # Click in the center of the element
                x = element["x"] + element["width"] / 2
                y = element["y"] + element["height"] / 2
                await self.page.mouse.click(x, y)
                print(f"👆 Clicked on element #{element_id}: {element_desc}")

            elif action == "type":
                input_text = decision.get("input_text", "")
                # Check if this is a sensitive field
                is_sensitive = self._is_sensitive_field(element)

                # Click the element first
                x = element["x"] + element["width"] / 2
                y = element["y"] + element["height"] / 2
                await self.page.mouse.click(x, y)

                # Clear any existing text
                await self.page.keyboard.press("Control+A")
                await self.page.keyboard.press("Backspace")

                # Type the text
                await self.page.keyboard.type(input_text)

                # Print with masked value if sensitive
                if is_sensitive:
                    print(
                        f"⌨️ Typed [REDACTED] into element #{element_id}: {element_desc}"
                    )
                else:
                    print(
                        f"⌨️ Typed '{input_text}' into element #{element_id}: {element_desc}"
                    )

            return True

        except Exception as e:
            print(f"❌ Error executing decision: {e}")
            return False

    def _get_element_description(self, element):
        """Get a descriptive name for an element"""
        # Try different properties in order of preference
        if element.get("text") and element["text"].strip():
            # Truncate long text
            text = element["text"].strip()
            if len(text) > 50:
                text = text[:47] + "..."
            return text

        if element.get("placeholder") and element["placeholder"].strip():
            return f"[Placeholder: {element['placeholder']}]"

        if element.get("name") and element["name"].strip():
            return f"[Name: {element['name']}]"

        if element.get("id_attr") and element["id_attr"].strip():
            return f"[ID: {element['id_attr']}]"

        if element.get("type") and element["type"].strip():
            return f"[{element['tag']} type={element['type']}]"

        # Fallback to tag name
        return f"[{element['tag']}]"

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

    async def run_test(self, url, goal, max_steps=10):
        """Run the test with the given URL and goal"""
        print(f"🌐 Starting test with URL: {url}")
        print(f"🎯 Goal: {goal}")

        # Navigate to the URL
        await self.page.goto(url)

        # Main loop
        while self.step_count < max_steps and not self.goal_achieved:
            self.step_count += 1
            print(f"\n📍 Step {self.step_count}/{max_steps}")

            # Verify we have a valid page
            if not self.page or not self.pages:
                print("⚠️ No valid page available, creating a new one")
                self.page = await self.context.new_page()
                self.pages.append(self.page)
                await self._setup_page_event_handlers(self.page)
                await self.page.goto(url)

            # Wait for the page to load
            await self.wait_for_page_load()

            # Take a screenshot
            screenshot_path = await self.take_screenshot()

            # Gather elements
            elements = await self.gather_page_elements()

            # Get current URL
            current_url = self.page.url

            # Check if goal has been achieved (dedicated check)
            if self.step_count > 1:  # Skip on first step
                await self.check_goal_completion(screenshot_path, goal, current_url)

                # If goal achieved, break the loop
                if self.goal_achieved:
                    print("🏆 Goal achieved! Test completed successfully.")
                    break

            # Ask AI for decision
            decision = await self.ask_ai_for_decision(
                screenshot_path, elements, goal, current_url
            )

            # Check if goal is achieved from decision
            if self.goal_achieved:
                print("🏆 Goal achieved! Test completed successfully.")
                break

            # Execute the decision
            success = await self.execute_decision(decision, elements)

            # Wait a bit for the action to take effect
            await asyncio.sleep(2)

        if not self.goal_achieved and self.step_count >= max_steps:
            print("⏱️ Maximum steps reached without achieving the goal")

        # Take a final screenshot
        await self.take_screenshot()

        return self.goal_achieved

    def _encode_image(self, image_path):
        """Encode image to base64 for API request"""
        import base64

        with open(image_path, "rb") as image_file:
            return base64.b64encode(image_file.read()).decode("utf-8")
