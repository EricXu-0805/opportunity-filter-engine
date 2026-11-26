"""Shared two-tab scenario for both an isolated service and a real synthetic guest."""
import asyncio
from playwright.async_api import expect

async def check_answers(mode,page,receiver,outcomes,set_outage,stored_row,profile_name):
    tabs=(page,receiver)
    lang='zh' if mode.startswith('racezh') else 'en'
    set_outage(True)
    await page.locator('#major').select_option('Electrical Engineering')
    await expect(page.get_by_test_id('retry-sync')).to_be_visible(timeout=25000)
    await receiver.locator('#major').select_option('Computer Engineering')
    keep = [tab.get_by_test_id('conflict-keep-mine') for tab in tabs]
    await expect(receiver.get_by_test_id('retry-sync').or_(keep[1]).first).to_be_visible(timeout=20000)
    set_outage(False)
    for index,tab in enumerate(tabs):
        await tab.bring_to_front()
        retry = tab.get_by_test_id('retry-sync')
        if not await keep[index].is_visible() and await retry.is_visible():
            try:
                await retry.click(timeout=2500)
            except Exception:
                await expect(keep[index]).to_be_visible(timeout=7500)
    messages = []
    for index,tab in enumerate(tabs):
        await expect(keep[index]).to_be_visible(timeout=30000)
        expected = 'Changed somewhere else' if lang == 'en' else '在别处改过了'
        message = await tab.locator('#profile-save-status').inner_text()
        messages.append(expected in message)
        print('Open choice',lang,index,'visible major',await tab.locator('#major').input_value(),repr(message),flush=True)
        for button in (keep[index],tab.get_by_test_id('conflict-use-cloud')):
            dims=await button.evaluate("(b)=>({width:innerWidth,height:b.getBoundingClientRect().height,line:parseFloat(getComputedStyle(b).lineHeight),pad:parseFloat(getComputedStyle(b).paddingTop)+parseFloat(getComputedStyle(b).paddingBottom)})")
            assert dims['width'] == 390 and dims['height']-dims['pad'] <= dims['line']*2+3,dims
        await tab.evaluate("""() => {window.receiptViews=[];window.statusHistory=[];window.receiptClicks=0;document.addEventListener('click',e=>{if(e.target.closest('[data-testid="conflict-keep-mine"]')){window.receiptClicks++;window.receiptClickTime=Date.now();window.beforeClickStatus=document.querySelector('#profile-save-status')?.innerText}},true);new MutationObserver(()=>{
            const msg=document.querySelector('#profile-save-status')?.innerText;
            if(msg && window.statusHistory.at(-1)!==msg && window.statusHistory.length<30) window.statusHistory.push(msg);
            const s = document.querySelector('[data-testid="conflict-stale"]');
            const retry=document.querySelector('[data-testid="retry-sync"]');
            const failed=/Saved on this device only|仅保存在本设备|没能同步/.test((document.querySelector('#profile-save-status')?.innerText || ''));
            if(window.receiptClicks && msg!==window.beforeClickStatus && (s || retry || failed)) window.receiptViews.push({stale:!!s,retry:!!retry,failed});
        }).observe(document.body,{subtree:true,childList:true,characterData:true,attributes:true});}""")
    outcomes.clear()
    staggered = mode.endswith('-staggered')
    second_available = True
    if staggered:
        await keep[0].click()
        await asyncio.sleep(.8)
        for i,t in enumerate(tabs):
            print('Before second attempt',i,await t.locator('#major').input_value(),repr(await t.locator('#profile-save-status').inner_text()),flush=True)
        second_available = await keep[1].is_visible()
        if second_available:
            try:
                await keep[1].click(timeout=500)
            except Exception:
                if await keep[1].is_visible():
                    raise
                second_available = False
        print('Choice still actionable after 0.8s', lang, second_available, flush=True)
    else:
        await asyncio.gather(*(button.click(timeout=3000) for button in keep))
    for button in keep:
        await expect(button).to_have_count(0,timeout=15000)
    await asyncio.sleep(2)
    views=[await tab.evaluate("window.receiptViews") for tab in tabs]
    saved=await stored_row()
    major=saved['profile_data']['major']
    for tab in tabs:
        await tab.bring_to_front()
        await expect(tab.locator('#student_name')).to_have_value(profile_name,timeout=45000)
        campus_picker = tab.get_by_test_id('university-card-uiuc')
        if await campus_picker.is_visible():
            await campus_picker.click()
            await tab.get_by_test_id('switcher-confirm').click()
            await expect(campus_picker).to_be_hidden(timeout=15000)
        await expect(tab.locator('#major')).to_have_value(major)
    print('Concurrent answers',lang,major,'write outcomes',outcomes,'observed stale/retry/failure', [[any(v[k] for v in vs) for k in ('stale','retry','failed')] for vs in views],flush=True)
    clicks = [await tab.evaluate('window.receiptClicks') for tab in tabs]
    print('Click receipts',clicks,'approved conflict explanation present',messages,flush=True)
    times = [await tab.evaluate('window.receiptClickTime ?? null') for tab in tabs]
    print('Click interval in ms', times[1]-times[0] if all(times) else None, flush=True)
    print('Ordered status history', [[v.replace('\n',' / ') for v in await tab.evaluate('window.statusHistory')] for tab in tabs],flush=True)
    assert all(messages), messages
    assert clicks == [1,int(second_available)] and outcomes == ['applied']
    if second_available:
        assert any(any(v['stale'] for v in vs) for vs in views)
    if staggered:
        assert major == 'Electrical Engineering'
    assert not any(v['retry'] or v['failed'] for vs in views for v in vs)
    await receiver.reload(wait_until='domcontentloaded')
    await expect(receiver.locator('#major')).to_have_value(major,timeout=45000)
    print('PASS double Keep, both tabs and reopened form agree, one account write;',lang,flush=True)
