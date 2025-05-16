#!/usr/bin/env python3
"""
BugNinja v3 - AI-Driven Web Testing Tool
A modular implementation with separate classes for different responsibilities
"""

import os
import asyncio
import json
import random
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple

import dotenv
from playwright.async_api import async_playwright, Page, Browser, BrowserContext
from openai import AsyncAzureOpenAI
from playwright_stealth import stealth_sync


class WebCrawler:
    """Handles all web interactions and element detection"""

    def __init__(self, headless: bool = True, output_dir: str = "./output"):
        self.headless = headless
        self.output_dir = Path(output_dir)
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self.pages: List[Page] = []
        self.cookie_consent_handled = {}

    async def start(self):
        """Initialize browser with stealth settings"""
        playwright = await async_playwright().start()

        # Launch browser with anti-detection settings
        self.browser = await playwright.chromium.launch(
            headless=self.headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-features=IsolateOrigins,site-per-process",
                "--no-sandbox",
                "--disable-web-security",
            ],
        )

        # Set up context with realistic browser fingerprint
        self.context = await self.browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            locale="en-US",
            timezone_id="America/New_York",
            has_touch=False,
            is_mobile=False,
            color_scheme="light",
            ignore_https_errors=True,
        )

        # Set up event listeners for new pages
        self.context.on("page", self._handle_new_page)

        # Create initial page
        self.page = await self.context.new_page()
        self.pages.append(self.page)
        await self._setup_page(self.page)

        print("🚀 Browser started with stealth mode")

    async def _handle_new_page(self, page: Page):
        """Handle a new page/tab being opened"""
        print("🔄 New tab/window detected")

        # Set up the new page
        await self._setup_page(page)

        # Add to our list of pages
        self.pages.append(page)

        # Switch to the new page
        self.page = page
        print(f"👉 Switched to new tab: {page.url}")

    async def _setup_page(self, page: Page):
        """Set up a new page with stealth and event handlers"""
        stealth_sync(page)
        page.on("close", lambda: asyncio.create_task(self._handle_page_close(page)))
        page.on("dialog", lambda dialog: asyncio.create_task(dialog.accept()))

    async def _handle_page_close(self, closed_page: Page):
        """Handle page closure and switch to another if needed"""
        print("🔄 Tab/window closed")

        if closed_page in self.pages:
            self.pages.remove(closed_page)

        # If the current page was closed, switch to the previous page
        if self.page == closed_page and self.pages:
            # Switch to the most recently used page
            self.page = self.pages[-1]
            print(f"👉 Switched back to tab: {self.page.url}")
        elif not self.pages:
            # If no pages are left, create a new one
            print("⚠️ No tabs left, creating a new one")
            self.page = await self.context.new_page()
            self.pages.append(self.page)
            await self._setup_page(self.page)

    async def stop(self):
        """Clean up browser resources"""
        if self.context:
            await self.context.close()
        if self.browser:
            await self.browser.close()

    async def navigate(self, url: str):
        """Navigate to URL and wait for load"""
        await self.page.goto(url)
        await self.wait_for_load()

    async def wait_for_load(self):
        """Wait for page to be fully loaded"""
        try:
            await self.page.wait_for_load_state("networkidle", timeout=10000)
        except:
            await self.page.wait_for_load_state("domcontentloaded")
            await asyncio.sleep(1)

    async def get_elements(self) -> List[Dict]:
        """Get all interactive elements with their coordinates and properties"""
        try:
            js_code = """
            () => {
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

                try {
                    const elements = [];
                    const selectors = 'a, button, input, select, textarea, [role="button"], [role="link"], [role="checkbox"], [onclick]';
                    
                    document.querySelectorAll(selectors).forEach(el => {
                        try {
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
                        } catch (elementError) {
                            console.error('Error processing element:', elementError);
                        }
                    });
                    
                    return elements;
                } catch (mainError) {
                    console.error('Error in main execution:', mainError);
                    return [];
                }
            }
            """

            elements = await self.page.evaluate(js_code)
            print(f"🔍 Found {len(elements)} interactive elements")
            return elements

        except Exception as e:
            print(f"⚠️ Error gathering elements: {e}")
            return []

    async def click_element(self, x: float, y: float):
        """Click at specific coordinates with human-like movement"""
        await self._move_mouse_naturally(x, y)
        await asyncio.sleep(random.uniform(0.1, 0.3))
        await self.page.mouse.click(x, y)

    async def type_text(self, x: float, y: float, text: str):
        """Type text at coordinates with human-like behavior"""
        await self._move_mouse_naturally(x, y)
        await self.page.mouse.click(x, y)
        await asyncio.sleep(random.uniform(0.2, 0.4))

        # Clear existing text
        await self.page.keyboard.press("Control+A")
        await self.page.keyboard.press("Backspace")
        await asyncio.sleep(random.uniform(0.1, 0.3))

        # Type with random delays
        for char in text:
            await self.page.keyboard.type(char)
            await asyncio.sleep(random.uniform(0.05, 0.15))

    async def _move_mouse_naturally(self, target_x: float, target_y: float):
        """Move mouse in a natural curve to target coordinates"""
        current = await self.page.evaluate(
            "() => ({ x: window.mouseX || 0, y: window.mouseY || 0 })"
        )
        start_x, start_y = current.get("x", 0), current.get("y", 0)

        # Create control point for quadratic bezier curve
        control_x = start_x + (target_x - start_x) * random.uniform(0.3, 0.7)
        control_y = start_y + (target_y - start_y) * random.uniform(0.3, 0.7)
        control_x += random.uniform(-50, 50)
        control_y += random.uniform(-50, 50)

        steps = 10
        for i in range(steps + 1):
            t = i / steps
            x = int(
                (1 - t) ** 2 * start_x + 2 * (1 - t) * t * control_x + t**2 * target_x
            )
            y = int(
                (1 - t) ** 2 * start_y + 2 * (1 - t) * t * control_y + t**2 * target_y
            )
            await self.page.mouse.move(x, y)
            await asyncio.sleep(random.uniform(0.01, 0.03))

    async def take_screenshot(self, step: int) -> str:
        """Take a screenshot and return the path"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = self.output_dir / f"step_{step}_{timestamp}.png"
        await self.page.screenshot(path=path)
        return str(path)


class AIController:
    """Handles all AI-related tasks and decision making"""

    def __init__(self):
        dotenv.load_dotenv()
        self.client = AsyncAzureOpenAI(
            api_key=os.getenv("AZURE_OPENAI_API_KEY"),
            api_version="2023-12-01-preview",
            azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
        )
        self.conversation_history = []

    async def make_decision(
        self, screenshot_path: str, elements: List[Dict], goal: str, url: str
    ) -> Dict:
        """Analyze current state and decide next action"""
        # Prepare messages for AI
        messages = self._prepare_messages(screenshot_path, elements, goal, url)

        # Get AI response
        response = await self.client.chat.completions.create(
            model=os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME", "gpt-4o"),
            messages=messages,
            response_format={"type": "json_object"},
            max_tokens=1000,
        )

        decision = json.loads(response.choices[0].message.content)
        self._log_decision(decision, elements)
        return decision

    def _prepare_messages(
        self, screenshot_path: str, elements: List[Dict], goal: str, url: str
    ) -> List[Dict]:
        """Prepare messages for AI with current state information"""
        system_message = {
            "role": "system",
            "content": """You are an AI web tester. Analyze the page and decide the next action.
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
            - For clicking, use the center_x and center_y coordinates provided
            - For typing, first click on the input field, then provide the text to type
            """,
        }

        user_message = {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": f"URL: {url}\nGoal: {goal}\n\nElements:\n{json.dumps(elements, indent=2)}",
                },
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/png;base64,{self._encode_image(screenshot_path)}"
                    },
                },
            ],
        }

        return [system_message] + self.conversation_history[-6:] + [user_message]

    def _log_decision(self, decision: Dict, elements: List[Dict]):
        """Log AI's decision for debugging"""
        action = decision.get("action", "unknown")
        coords = decision.get("coordinates", {})
        x, y = coords.get("x", 0), coords.get("y", 0)

        if action == "click":
            print(f"🤖 Decided to click at coordinates ({x}, {y})")
        elif action == "type":
            text = decision.get("input_text", "")
            print(f"🤖 Decided to type '{text}' at coordinates ({x}, {y})")

        print(f"💭 Reasoning: {decision.get('reasoning', 'No reasoning provided')}")

    def _encode_image(self, path: str) -> str:
        """Encode image to base64"""
        import base64

        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode()


class BugNinja:
    """Main class that orchestrates the testing process"""

    def __init__(self, headless: bool = True, output_dir: str = "./output"):
        self.crawler = WebCrawler(headless, output_dir)
        self.ai = AIController()
        self.step_count = 0
        self.goal_achieved = False

    async def run_test(self, url: str, goal: str, max_steps: int = 10):
        """Run the main testing loop"""
        try:
            print(f"🌐 Starting test for URL: {url}")
            print(f"🎯 Goal: {goal}")

            await self.crawler.start()
            await self.crawler.navigate(url)

            # Track goal achievement status
            pending_goal_achieved = False
            pending_confidence = 0.0

            while self.step_count < max_steps and not self.goal_achieved:
                self.step_count += 1
                print(f"\n📍 Step {self.step_count}/{max_steps}")

                # Get current state
                elements = await self.crawler.get_elements()
                screenshot = await self.crawler.take_screenshot(self.step_count)

                # Get current URL (which may have changed due to navigation or new tabs)
                current_url = self.crawler.page.url
                print(f"🌐 Current URL: {current_url}")

                # Check if we had a pending goal achievement from previous step
                if pending_goal_achieved and pending_confidence >= 0.8:
                    self.goal_achieved = True
                    print(f"🎉 Goal achieved with confidence {pending_confidence:.2f}")
                    print("📸 Final state captured in screenshot")
                    break

                # Get AI decision
                decision = await self.ai.make_decision(
                    screenshot, elements, goal, current_url
                )

                # Store goal achievement status for next iteration
                pending_goal_achieved = decision.get("goal_achieved", False)
                pending_confidence = decision.get("confidence", 0)

                # Execute decision
                coords = decision.get("coordinates", {})
                x, y = coords.get("x", 0), coords.get("y", 0)

                if decision.get("action") == "click":
                    await self.crawler.click_element(x, y)
                elif decision.get("action") == "type":
                    await self.crawler.type_text(x, y, decision.get("input_text", ""))

                # Wait for page to load after action
                await self.crawler.wait_for_load()
                await asyncio.sleep(
                    1
                )  # Additional delay to ensure page is fully rendered

            # Take one final screenshot if we completed successfully
            if self.goal_achieved:
                final_screenshot = await self.crawler.take_screenshot(
                    self.step_count + 1
                )
                print(f"📸 Final screenshot saved: {final_screenshot}")

            print("✅ Test completed" if self.goal_achieved else "❌ Test failed")
            await self.crawler.stop()

        except Exception as e:
            print(f"❌ Error during test: {e}")
            traceback.print_exc()
            await self.crawler.stop()
            return False

        return self.goal_achieved


if __name__ == "__main__":
    # Example usage
    async def main():
        bugninja = BugNinja(headless=False)
        await bugninja.run_test(
            url="https://www.quino.ai",
            goal="Log in with google to the site",
        )

    asyncio.run(main())
