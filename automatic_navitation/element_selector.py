#!/usr/bin/env python3
"""
Element Selector - Functions to display and select elements from a webpage.
"""

import os
import sys
from typing import List, Dict, Any, Optional

from web_analyzer import ActionableElement


def display_top_elements(elements: List[ActionableElement], count: int = 10) -> None:
    """Display the top elements based on hierarchy level.

    Args:
        elements (List[ActionableElement]): List of elements to display
        count (int): Number of elements to display
    """
    # Ensure we don't try to display more elements than we have
    count = min(count, len(elements))

    # Create a nice display header
    print("\n" + "=" * 80)
    print(f"TOP {count} ELEMENTS BY HIERARCHY LEVEL".center(80))
    print("=" * 80)
    print(
        f"{'#':<3} | {'LEVEL':<5} | {'TYPE':<15} | {'POSITION':<15} | {'TEXT/DESCRIPTION':<40}"
    )
    print("-" * 80)

    # Display each element with its hierarchy level and relevant information
    for i, elem in enumerate(elements[:count]):
        # Get a description (text or selector)
        description = elem.text or elem.selector
        if len(description) > 40:
            description = description[:37] + "..."

        # Format position as x,y
        position = f"{int(elem.location['x'])},{int(elem.location['y'])}"

        # Print the element info
        print(
            f"{i:<3} | {elem.hierarchy_level:<5} | {elem.element_type:<15} | {position:<15} | {description:<40}"
        )

    print("-" * 80)


def get_user_selection(elements: List[ActionableElement]) -> str:
    """Get user selection from displayed elements.

    Args:
        elements (List[ActionableElement]): List of available elements

    Returns:
        str: User's selection (element index, "exit", "back", "url", or "reload")
    """
    # Print options
    print("\nACTIONS:")
    print("0-9: Select an element by number")
    print("b: Go back in history")
    print("r: Reload current page")
    print("u: Enter a new URL")
    print("x: Exit program")

    while True:
        # Get user input
        selection = input("\nEnter your choice: ").strip().lower()

        # Check if it's a valid element index
        if selection.isdigit():
            index = int(selection)
            if 0 <= index < len(elements):
                return str(index)
            else:
                print(
                    f"Invalid selection: Please choose a number between 0 and {len(elements)-1}"
                )
                continue

        # Check for special commands
        if (
            selection == "x"
            or selection == "exit"
            or selection == "q"
            or selection == "quit"
        ):
            return "exit"
        elif selection == "b" or selection == "back":
            return "back"
        elif selection == "u" or selection == "url":
            return "url"
        elif selection == "r" or selection == "reload":
            return "reload"
        else:
            print("Invalid selection. Please try again.")


def ment_details(element: ActionableElement) -> None:
    """Print detailed information about an element.

    Args:
        element (ActionableElement): The element to display details for
    """
    print("\n" + "=" * 80)
    print("ELEMENT DETAILS".center(80))
    print("=" * 80)

    print(f"Type:            {element.element_type}")
    print(f"Text:            {element.text}")
    print(f"Selector:        {element.selector}")
    print(f"Hierarchy Level: {element.hierarchy_level}")
    print(f"DOM Depth:       {element.dom_depth}")
    print(f"Visible:         {element.is_visible}")

    print("\nLocation:")
    print(f"  X:      {element.location['x']}")
    print(f"  Y:      {element.location['y']}")
    print(f"  Width:  {element.location['width']}")
    print(f"  Height: {element.location['height']}")

    print("\nAttributes:")
    for key, value in element.attributes.items():
        # Skip internal attributes that start with underscore
        if not key.startswith("_"):
            print(f"  {key}: {value}")

    print("=" * 80)
