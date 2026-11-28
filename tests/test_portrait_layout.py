"""Keep opportunity actions visible in a portrait desktop window."""

from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

CSS = Path(__file__).resolve().parents[1] / "web" / "style.css"


@pytest.mark.parametrize("width,height", [(900, 1440), (720, 1200), (1280, 900)])
def test_opportunity_actions_fit_window(width, height):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={"width": width, "height": height})
            page.set_content(
                """<aside class="sidebar">JobPilot</aside>
                <main class="main"><section class="panel queue-panel">
                <div class="table-wrap"><table class="jobs-table">
                <thead><tr><th>Opportunity</th><th>Posted</th><th>Fit</th>
                <th>Review</th><th>Applied?</th><th>Remove</th></tr></thead>
                <tbody><tr><td><div class="job-cell"><div class="company-avatar">A</div>
                <div><a class="job-title">Security Engineer</a>
                <div class="job-sub">Example Company · Indeed</div></div></div></td>
                <td class="freshness">Today</td><td><div class="fit-cell">91%</div></td>
                <td><button class="button secondary compact">Review</button></td>
                <td><button class="button track-button compact">Applied?</button></td>
                <td><button class="button quiet compact">Remove</button></td>
                </tr></tbody></table></div></section></main>"""
            )
            page.add_style_tag(path=str(CSS))
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            geometry = page.evaluate(
                """() => {
                    const wrap = document.querySelector('.table-wrap').getBoundingClientRect();
                    const row = document.querySelector('tbody tr').getBoundingClientRect();
                    const buttons = [...document.querySelectorAll('tbody button')];
                    return {wrap: [wrap.left, wrap.right], row: [row.left, row.right],
                    buttons: buttons.map(button => {
                        const box = button.getBoundingClientRect();
                        return [box.left, box.right, box.width];
                    })};
                }"""
            )
            assert geometry["row"][1] <= geometry["wrap"][1] + 1, geometry
            assert all(
                box[2] >= 60 and box[0] >= geometry["wrap"][0] and box[1] <= geometry["wrap"][1] + 1
                for box in geometry["buttons"]
            ), geometry
        finally:
            browser.close()
