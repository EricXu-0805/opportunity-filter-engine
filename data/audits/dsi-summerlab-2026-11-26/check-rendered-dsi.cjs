const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require(require.resolve("playwright", { paths: [path.join(process.cwd(), "frontend")] }));
const [site, expectedSha, destination, clockFile] = process.argv.slice(2);
const ids = ["uchicago-8cd2def060b6", "sro-d6b78515"];
const official = "https://datascience.uchicago.edu/education/summerlab/program-details/";
const scope = "mvp-core-close-v1-contact-trust-v1-faculty-trust-v1-target-truth-v2";
const assert = require("node:assert/strict");
const simulated = Boolean(clockFile);
assert(!simulated || ["localhost","127.0.0.1"].includes(new URL(site).hostname));
async function main() {
  const result = { release_sha: expectedSha, site, simulated: simulated, source_states: [] };
  const browser = await chromium.launch({ headless: true });
  try {
    const context = await browser.newContext({locale:"en-US", timezoneId:"America/Chicago"});
    if (simulated) {
      await context.addInitScript(() => {
        localStorage.setItem("ofe_onboarding_seen", "1");
        localStorage.setItem("ofe_lang", "en");
        sessionStorage.setItem("ofe_school_confirm_deferred", "1");
      });
    }
    for (const stamp of (simulated ? ["2027-01-12T05:58:59Z", "2027-01-12T05:59:00Z", "2027-01-12T13:59:00Z"] : [null])) {
      if (simulated) fs.writeFileSync(clockFile, stamp);
      const health = await (await fetch(site+"/api/health")).json();
      assert.equal(health.release_sha,expectedSha);
      const state = { tested_clock:stamp,rows:[] };
      for (const id of ids) {
        const page=await context.newPage();
        try {
          if (simulated) await page.clock.setFixedTime(new Date(stamp));
          const url=site+"/opportunities/"+id;
          let response=await page.goto(url,{waitUntil:"domcontentloaded",timeout:65000});
          const unavailable=page.getByRole("heading",{name:"This opportunity is temporarily unavailable"});
          const back=page.getByRole("link",{name:"Back to matches",exact:true});
          await back.or(unavailable).first().waitFor({timeout:45000});
          if (await unavailable.isVisible()) {
            await page.getByRole("button",{name:"Retry",exact:true}).click();
            await back.waitFor({timeout:45000});
          }
          assert.equal(response.status(),200);
          const main=page.getByRole("main");
          await main.getByRole("link",{name:"Back to matches",exact:true}).waitFor({timeout:35000});
          assert.equal(await page.locator("html").getAttribute("data-release-sha"),expectedSha);
          const text=await main.innerText();
          const links=await main.getByRole("link").evaluateAll(items=>items.map(a=>({name:a.innerText,href:a.getAttribute("href")})));
          const apply=links.filter(a=>/^(apply now|apply)$/i.test(a.name));const cites=links.filter(a=>a.href===official);
          const apiResp=await fetch(site+"/api/opportunities/"+id+"?_release_scope="+encodeURIComponent(scope));
          assert.equal(apiResp.status,200); const record=await apiResp.json();
          const open=stamp===null ? Boolean(record.target_truth.actionable) : stamp.endsWith("05:58:59Z");
          const row={id,title:await main.getByRole("heading",{level:1}).innerText(),
                     api_actionable:record.target_truth.actionable,apply_action_links:apply,university_citations:cites,
                     stipend_5600:text.includes("$5,600"),conditional_1800:text.includes("$1,800"),
                     source_funding_url:record.detail_fields.fields.funding.quotes.compensation?.source_url,
                     official_deadline:record.deadline,cutoff:record.application_closes_at,closed_message:/closed|deadline has passed/i.test(text)};
          state.rows.push(row);
          console.log(stamp,id,JSON.stringify(row));
          assert.equal(row.api_actionable,open);
          assert.equal(row.official_deadline,"2027-01-11");
          assert.equal(row.cutoff,"2027-01-11T23:59:00-06:00");
          assert.equal(row.source_funding_url,official);
          assert.equal(apply.length>0,open);
          if(open) {
            assert(row.stipend_5600 && row.conditional_1800);assert(cites.length>0);
            if (process.env.DSI_VERIFY_WORK_AUTH === "1") {
              const eligibility=record.detail_fields.fields.eligibility;
              assert.equal(eligibility.explicit.citizenship,"not_required");
              assert.equal(eligibility.explicit.international_students,"yes");
              assert.equal(eligibility.explicit.work_authorization_notes,"All participants need U.S. work authorization and documentation for their stipend.");
              assert(text.includes("No citizenship requirement"));
              assert(text.includes("Open to international students"));
              assert(text.includes(eligibility.explicit.work_authorization_notes));
              assert(text.includes("Selected NSF-funded undergraduates who are U.S. citizens or permanent residents"));
              row.eligibility = {};
              for (const field of ["citizenship","international_students","work_authorization_notes"]) {
                assert.equal(eligibility.quotes[field].source_url,"https://datascience.uchicago.edu/education/summerlab/faq/");
                row.eligibility[field]={value:eligibility.explicit[field],source:eligibility.quotes[field].source_url};
              }
              const faq=links.filter(l=>l.href==="https://datascience.uchicago.edu/education/summerlab/faq/");
              assert(faq.length>0);row.rendered_faq_citations=faq.length;
            }
          }
          else {assert(row.closed_message);assert(links.some(l=>l.href?.includes("uchicago.edu/") || l.href?.includes("researchops.web.illinois.edu/")));}
        } finally {await page.close();}
      }
      result.source_states.push(state);
    }
    const final = await (await fetch(site+"/api/health")).json();
    assert.equal(final.release_sha,expectedSha);result.same_release_after=true;
    result.observed_utc=new Date().toISOString();fs.writeFileSync(destination,JSON.stringify(result,null,2)+"\n");
  } finally {await browser.close();if(simulated && fs.existsSync(clockFile)) fs.unlinkSync(clockFile);}
}
main().catch(e=>{console.error(e);process.exitCode=1;});
