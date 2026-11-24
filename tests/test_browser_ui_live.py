import asyncio
from pathlib import Path
from playwright.async_api import async_playwright

ARTIFACTS_DIR = Path("/home/vanrajsinh/.gemini/antigravity/brain/3bf639a0-89ed-4164-aa5c-e07164b5a316")

async def run_live_browser_tests():
    print("🚀 Starting automated browser UI testing on http://127.0.0.1:8000 ...")
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context(viewport={"width": 1400, "height": 900})
        page = await context.new_page()

        # Step 1: Navigate to Dashboard
        await page.goto("http://127.0.0.1:8000", wait_until="domcontentloaded")
        await page.wait_for_timeout(1000)
        print("✓ Page loaded.")

        # Step 2: Check Top Bar Watch Bot toggle
        watch_bot_cb = await page.query_selector("#watch-bot-checkbox")
        is_checked = await watch_bot_cb.is_checked() if watch_bot_cb else False
        watch_label = await page.inner_text("#watch-bot-label") if await page.query_selector("#watch-bot-label") else ""
        print(f"✓ Watch Bot Toggle: checked={is_checked}, label='{watch_label}'")
        assert is_checked, "Watch Bot toggle should be checked/enabled by default!"

        # Step 3: Navigate to "Apply Portals & Links"
        nav_btn = await page.query_selector("#nav-apply-portals")
        assert nav_btn is not None, "Navigation button #nav-apply-portals not found!"
        await nav_btn.click()
        
        # Wait for portal cards to load from API
        await page.wait_for_selector(".portal-card", timeout=45000)
        print("✓ Portal cards loaded from API.")

        # Step 4: Verify Metric Cards
        stat_total = await page.inner_text("#stat-apply-total")
        stat_ext = await page.inner_text("#stat-apply-external")
        stat_li_ext = await page.inner_text("#stat-apply-linkedin-ext")
        stat_li_easy = await page.inner_text("#stat-apply-linkedin-easy")
        print(f"✓ Metric Cards: Total={stat_total}, Direct ATS={stat_ext}, LinkedIn External={stat_li_ext}, Easy Apply={stat_li_easy}")

        # Capture View 1: Main Portals View
        shot1 = ARTIFACTS_DIR / "browser_portals_overview.png"
        await page.screenshot(path=str(shot1), full_page=False)
        print(f"📸 Captured: {shot1.name}")

        # Step 5: Filter by Greenhouse
        # Wait for dynamic platform pills to render
        await page.wait_for_selector("button.platform-pill-btn", timeout=5000)
        gh_pill = await page.query_selector("button.platform-pill-btn[data-platform='Greenhouse']")
        if gh_pill:
            await gh_pill.click()
            await page.wait_for_selector(".portal-card", timeout=30000)
            print("✓ Clicked 'Greenhouse' filter pill button.")
        else:
            await page.select_option("#portal-platform-select", "Greenhouse")
            await page.wait_for_selector(".portal-card", timeout=30000)
            print("✓ Selected 'Greenhouse' via platform dropdown.")

        # Capture View 2: Filtered Greenhouse Cards
        shot2 = ARTIFACTS_DIR / "browser_greenhouse_filtered.png"
        await page.screenshot(path=str(shot2), full_page=False)
        print(f"📸 Captured: {shot2.name}")

        # Step 6: Verify Greenhouse cards have NO LinkedIn button
        cards = await page.query_selector_all("#portals-cards-grid .portal-card")
        print(f"✓ Found {len(cards)} Greenhouse portal cards rendered.")
        assert len(cards) > 0, "Expected at least 1 Greenhouse card to be rendered!"

        greenhouse_has_linkedin_btn = False
        card_titles = []
        for i, card in enumerate(cards[:6]):
            title_el = await card.query_selector("h3")
            card_title = (await title_el.inner_text()).strip() if title_el else f"Card #{i}"
            card_titles.append(card_title)

            # Check if any button or link inside contains "LinkedIn"
            li_btn = await card.query_selector("a:has-text('LinkedIn'), button:has-text('LinkedIn')")
            if li_btn:
                is_vis = await li_btn.is_visible()
                if is_vis:
                    greenhouse_has_linkedin_btn = True
                    print(f"⚠ Card '{card_title}' unexpectedly has a visible LinkedIn button!")
            
            # Verify required action buttons exist
            apply_form_btn = await card.query_selector("a:has-text('Apply Form')")
            apply_bot_btn = await card.query_selector("button.btn-apply-single")
            details_btn = await card.query_selector("button.btn-view-desc")
            
            assert apply_form_btn is not None, f"Card '{card_title}' missing 'Apply Form ↗' button!"
            assert apply_bot_btn is not None, f"Card '{card_title}' missing 'Apply ⚡' button!"
            assert details_btn is not None, f"Card '{card_title}' missing 'View Details' button!"

        if not greenhouse_has_linkedin_btn:
            print(f"✅ CONFIRMED: ZERO Greenhouse cards contain a LinkedIn button across {len(card_titles)} inspected cards!")
        else:
            raise AssertionError("FAILURE: Greenhouse cards still contain a LinkedIn button!")

        # Step 7: Test "View Details" Modal on first Greenhouse card
        first_desc_btn = await cards[0].query_selector("button.btn-view-desc")
        assert first_desc_btn is not None, "View Details button not found on first card!"
        await first_desc_btn.click()
        await page.wait_for_timeout(1000)
        
        modal = await page.query_selector("#job-modal-overlay")
        is_modal_vis = await modal.is_visible() if modal else False
        print(f"✓ Job Details Modal opened: visible={is_modal_vis}")
        assert is_modal_vis, "Modal overlay failed to open!"

        # Verify Modal has NO LinkedIn button for Greenhouse job
        modal_li = await page.query_selector("#modal-linkedin-link")
        is_modal_li_vis = await modal_li.is_visible() if modal_li else False
        print(f"✓ Modal LinkedIn button: visible={is_modal_li_vis} (expected False)")
        assert not is_modal_li_vis, "Modal unexpectedly shows LinkedIn button for Greenhouse job!"

        shot3 = ARTIFACTS_DIR / "browser_greenhouse_modal.png"
        await page.screenshot(path=str(shot3), full_page=False)
        print(f"📸 Captured: {shot3.name}")

        # Close modal
        close_btn = await page.query_selector("#job-modal-close")
        if close_btn:
            await close_btn.click()
            await page.wait_for_timeout(500)
            print("✓ Modal closed cleanly.")

        await browser.close()
        print("🎉 ALL BROWSER UI VERIFICATION TESTS PASSED SUCCESSFULLY!")

asyncio.run(run_live_browser_tests())
