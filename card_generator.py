#!/usr/bin/env python3
import os
import re
from pathlib import Path


def generate_card():
    print("\n" + "=" * 40)
    print("  CARD TEMPLATE GENERATOR")
    print("=" * 40 + "\n")

    # Get card details with examples
    print(
        "Enter card details (press Enter to use default examples shown in [brackets]):"
    )

    title = input("Card Title (e.g., 'Netflix'): ").strip()
    while not title:
        print("Title is required!")
        title = input("Card Title: ").strip()

    icon = input(
        "Icon URL/path (e.g., 'https://example.com/icon.png' or '/static/icons/app.png'): "
    ).strip()
    while not icon:
        print("Icon is required!")
        icon = input("Icon URL/path: ").strip()

    url = input("Action URL (e.g., 'https://service.com' or '/steam'): ").strip()
    while not url:
        print("URL is required!")
        url = input("Action URL: ").strip()

    position = input(
        "Position number (optional, e.g., '1' for first position) [blank for random]: "
    ).strip()
    handler = input(
        "Handler type (optional, e.g., 'streaming', 'location') [blank for default]: "
    ).strip()

    # Ask about JavaScript
    print("\nJavaScript for this card (press Enter twice to finish):")
    print("Example: document.getElementById('myCard').addEventListener('click', ...)")
    js_lines = []
    while True:
        line = input("JS> ").strip()
        if not line and not js_lines:
            break
        if not line and js_lines:
            break
        js_lines.append(line)

    # Generate filename
    safe_title = re.sub(r"[^\w\-]", "_", title.lower())
    filename = f"{safe_title}.html"
    filepath = Path("templates/menu") / filename

    # Build template
    template = f"""<!-- TITLE: {title} -->
<!-- ICON: {icon} -->
<!-- URL: {url} -->"""

    if position:
        template += f"\n<!-- POSITION: {position} -->"
    if handler:
        template += f"\n<!-- HANDLER: {handler} -->"

    template += f"""
<div class="col">
  <div class="card h-100 text-center" {'id="' + safe_title + '_card"' if js_lines else f"onclick=\"openStreamingApp('{url}')\""}>
    <img src="{icon}" 
         class="card-img-top mx-auto mt-3" 
         alt="{title}">
    <div class="card-body">
      <h5 class="card-title">{title}</h5>
    </div>
  </div>
</div>"""

    if js_lines:
        template += "\n<script>\n" + "\n".join(js_lines) + "\n</script>"

    # Save to file
    os.makedirs("templates/menu", exist_ok=True)
    with open(filepath, "w") as f:
        f.write(template)

    print(f"\n✅ Card template saved to: {filepath}\n")
    print("Generated template:")
    print("=" * 40)
    print(template)
    print("=" * 40)


if __name__ == "__main__":
    while True:
        generate_card()
        if input("\nGenerate another card? (y/n) ").strip().lower() != "y":
            break
