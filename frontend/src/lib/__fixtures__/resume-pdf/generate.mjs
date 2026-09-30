// Regenerates the résumé PDF fixtures with Chromium's page.pdf, the way a
// student's browser or a web résumé builder prints them. Run from frontend/:
//   node src/lib/__fixtures__/resume-pdf/generate.mjs
// The three persona files follow the recipes of the 2026-09-30 stranger walk
// (their wrap points are the ones the walk reported); resume-layouts.pdf adds a
// sidebar layout, list bullets drawn as graphics, right-aligned dates, a
// one-item-per-line list and justified text split at soft hyphens.
import { readFileSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright';

const OUT = dirname(fileURLToPath(import.meta.url));

const PERSONA = readFileSync(join(OUT, 'persona.txt'), 'utf8');

const esc = (s) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
const HEADINGS = new Set(['EDUCATION', 'EXPERIENCE', 'PROJECTS', 'SKILLS']);

const fixtures = {
  // Cold-email walk: one paragraph per line, Helvetica (fi ligatures), 0.7in.
  'resume-ce2.pdf': {
    body: `<style>body{font-family:Helvetica,Arial,sans-serif;font-size:10.5pt;line-height:1.35;margin:0}p{margin:0 0 3pt 0}</style>`
      + PERSONA.split('\n').map((line) => `<p>${esc(line)}</p>`).join(''),
    pdf: { margin: { top: '0.6in', bottom: '0.6in', left: '0.7in', right: '0.7in' } },
  },
  // Target-résumé walk: one pre-wrap block with no paragraph spacing, 0.5in.
  'resume-tr04.pdf': {
    body: `<style>@page{size:Letter;margin:0.5in}body{font-family:Arial,Helvetica,sans-serif;font-size:10pt;line-height:1.35;margin:0}pre{font-family:inherit;white-space:pre-wrap;margin:0}</style><pre>${esc(PERSONA)}</pre>`,
    pdf: {},
  },
  // Renovate walk: bold headings, larger name, 1in margins ("integrated-" wraps).
  'resume-renovate.pdf': {
    body: `<style>body{font-family:Helvetica,Arial,sans-serif;font-size:10.5pt;margin:0}p{margin:0 0 3pt 0;line-height:1.3}.name{font-size:13pt;font-weight:bold}.h{font-weight:bold;margin-top:9pt}</style>`
      + PERSONA.split('\n').map((line, i) => {
        if (i === 0) return `<p class="name">${esc(line)}</p>`;
        return HEADINGS.has(line) ? `<p class="h">${esc(line)}</p>` : `<p>${esc(line)}</p>`;
      }).join(''),
    pdf: { margin: { top: '1in', bottom: '1in', left: '1in', right: '1in' } },
  },
  'resume-layouts.pdf': {
    body: `<style>
      body{font-family:Helvetica,Arial,sans-serif;font-size:10pt;line-height:1.3;margin:0}
      .page{display:flex;gap:18pt;break-after:page}
      aside{width:150pt;flex:none} .narrow{width:110pt} main{flex:1}
      h1{font-size:15pt;margin:0 0 4pt} h2{font-size:10.5pt;text-transform:uppercase;margin:10pt 0 3pt}
      p{margin:0 0 3pt} .tight p,.tight li,.tight h2{margin:0} ul{margin:0 0 4pt;padding-left:12pt}
      .row{display:flex;justify-content:space-between;font-weight:bold}
      .sub{display:flex;justify-content:space-between;font-style:italic}
      .plain{display:flex;justify-content:space-between}
      .justify{text-align:justify}
    </style>
    <div class="page">
      <aside>
        <h1>Priya Natarajan</h1>
        <p>priya.natarajan.test@example.com</p><p>(217) 555-0142</p><p>Champaign, IL</p><p>github.com/priya-test</p>
        <h2>Education</h2>
        <p>University of Illinois Urbana-Champaign</p>
        <p>B.S. in Bioengineering, Aug 2024 - May 2028</p>
        <p>Relevant coursework: Signals and Systems, Biomedical Imaging, Fluid Mechanics, Differential Equations</p>
        <h2>Skills</h2>
        <p>Python, MATLAB, NumPy, SolidWorks, LabVIEW, Git</p>
      </aside>
      <main>
        <h2>Research Experience</h2>
        <div class="row"><span>Undergraduate Researcher, Tissue Mechanics Lab</span><span>Sep 2025 - Present</span></div>
        <div class="sub"><span>University of Illinois Urbana-Champaign</span><span>Urbana, IL</span></div>
        <ul>
          <li>Designed an efficient finite-element workflow that reduced the fluid-flow simulation time of affine tissue models from six hours to forty minutes.</li>
          <li>Profiled official offline benchmarks and flagged five configuration files with conflicting boundary conditions.</li>
        </ul>
        <h2>Work Experience</h2>
        <div class="row"><span>Engineering Intern, Midwest Medical Devices</span><span>May 2025 - Aug 2025</span></div>
        <ul>
          <li>Automated the calibration log for twelve flow sensors and cut the weekly review from three hours to thirty minutes.</li>
          <li>Wrote first-draft test fixtures.</li>
        </ul>
      </main>
    </div>
    <div class="page tight">
      <aside class="narrow">
        <h2>Tools</h2>
        <p>Python</p><p>SolidWorks</p><p>LabVIEW</p><p>MATLAB</p><p>Git</p>
        <h2>Languages</h2>
        <p>English</p><p>Spanish</p>
      </aside>
      <main>
        <h2>Experience</h2>
        <div class="plain"><span>Research Intern, Biomechanics Lab</span><span>Jun 2025 - Aug 2025</span></div>
        <div class="plain"><span>University of Illinois</span><span>Urbana, IL</span></div>
        <ul>
          <li>Built a gait-analysis toolkit in Python used by eleven graduate students across two labs and three</li>
          <li>Collected force-plate recordings from twenty volunteers under an approved protocol with the lab manager</li>
          <li>Presented weekly results</li>
        </ul>
        <h2>Summary</h2>
        <p class="justify">Mechanical engineering student who compares wearable sensors for rehabilitation robotics and reports calibration, robustness and inter&shy;pretability results with counter&shy;factual checks for every study.</p>
        <p>Seeking a research position for Summer 2026</p>
      </main>
    </div>`,
    pdf: { margin: { top: '0.5in', bottom: '0.5in', left: '0.5in', right: '0.5in' } },
  },
};

const browser = await chromium.launch({ headless: true });
try {
  const page = await browser.newPage();
  for (const [name, spec] of Object.entries(fixtures)) {
    await page.setContent(`<!doctype html><html lang="en"><head><meta charset="utf-8"></head><body>${spec.body}</body></html>`);
    writeFileSync(join(OUT, name), await page.pdf({ format: 'Letter', ...spec.pdf }));
  }
} finally {
  await browser.close();
}
