"""Add read-only assertions about the experience picker to the existing real two-tab switch test."""
from pathlib import Path
p=Path('product/frontend/e2e/cloud-save-scenarios.spec.ts')
s=p.read_text(); a=s.index("  test('a guest who opens the sign-in link in a new tab keeps the account profile");b=s.index("\n  test(",a+10);case=s[a:b]
def insert(needle,addition):
    global case
    assert case.count(needle)==1,needle
    case=case.replace(needle,needle+'\n'+addition)
before="      const { modal } = await requestLink(page, email);"
assert case.count(before)==1
case=case.replace(before, '''      const sampleEmployer = 'First visitor practice employer';
      const library = page.locator('#experience-library');
      const importer = library.locator('details').filter({ has: page.getByText('Import LinkedIn experience', { exact: true }) });
      await importer.locator(':scope > summary').click();
      await importer.locator('input[type="file"]').setInputFiles({name:'Positions.csv',mimeType:'text/csv',buffer:Buffer.from('Company Name,Title,Description\\n'+sampleEmployer+',Practice analyst,Reviewed a mock report\\n')});
      await importer.getByRole('button',{name:'Preview experiences',exact:true}).click();
      await expect(importer.getByLabel('Company',{exact:true})).toHaveValue(sampleEmployer);
      console.log('First guest preview visible before changing owner; no import confirmation');
'''+before)
insert("      await expect(page.locator('#student_name')).not.toHaveValue(guest.name);",'''      await expect(importer.locator('fieldset')).toHaveCount(0);
      await expect(page.getByDisplayValue?.('dummy') ?? page.locator('input[value="First visitor practice employer"]')).toHaveCount(0);
      console.log('Second-tab owner switch discarded the first guest work preview before reload');'''.replace("page.getByDisplayValue?.('dummy') ?? ",''))
insert('      await expectForm(page, ACCOUNT_PROFILE);', '''      await expect(page.locator('#experience-library').getByText('Import LinkedIn experience',{exact:true})).toBeVisible();
      await expect(page.locator('input[value="First visitor practice employer"]')).toHaveCount(0);
      const accountRow = await profileRows(http, account.uid);
      expect(JSON.stringify(accountRow)).not.toContain(sampleEmployer);
      console.log('Account profile read completed; original profile and new-owner picker preserved; no prior-guest export persisted');''')
p.write_text(s[:a]+case+s[b:]);
