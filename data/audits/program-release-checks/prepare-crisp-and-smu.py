from pathlib import Path
import subprocess,sys
p=Path("data/audits/verify_m23_manual_20261126.py")
sha=sys.argv[1]
assert len(sha)==40 and set(sha)<=set("0123456789abcdef")
s=subprocess.check_output(["git","show","76afc3cca:"+str(p)],text=True)
s=s.replace("743e6fa6e6b8d56c39e5c2eb29a92a4fcdc16d7f",sha)
# The SMU landing page links its program-specific page, which states the
# funding and student requirements; ETAP supplies the actual dated window.
s=s.replace('research-experiences-undergraduates\']),', 'research-experiences-undergraduates/data-science-reu\']),')
s=s.replace('                        result[url]["date_lines"]=', '''                        if "acs-cancer-research-internship.html" in url:
                            assert response.ok and "Jan. 31, 2027" in body and "3.2" in body
                        if "data-science-reu" in url:
                            assert response.ok and "$5600 stipend" in body and "U.S. citizen or permanent resident" in body
                            assert "social science" in body.lower() and "2447670" in body
                        result[url]["date_lines"]=''')
s=s.replace('                        result[url]={"source_visit":str(exc)[:300]}', '''                        result[url]={"source_visit":str(exc)[:300]}
                        if url == etap or "data-science-reu" in url or "acs-cancer-research-internship.html" in url:
                            errors[url] = str(exc)[:500]''')
s=s.replace('                assert d["id"]==oid','''                assert d["id"]==oid
                crisp = oid == "sro-3ec4ea4e"
                expected = "2027-01-31" if crisp else "2027-02-22"
                opens = "2026-11-15" if crisp else "2026-11-19"
                page_url = "https://cancer.iu.edu/education/summer/acs-cancer-research-internship.html" if crisp else etap
                assert (d["deadline"],d["deadline_is_estimate"],d["is_rolling"])==(expected,False,False)
                assert d["application_opens"]["on"]==opens and d["application_opens"]["source_url"]==page_url
                fields=d["detail_fields"]["fields"]
                assert fields["timing"]["quotes"]["deadline"]["source_url"]==page_url
                if crisp:
                    assert d["eligibility"]["min_gpa"]==3.2 and d["paid"]=="yes"
                    assert d["location"]=="Indianapolis, IN" and d["remote_option"]=="no"
                else:
                    assert d["eligibility"]["skills_required"]==[] and d["eligibility"]["preferred_year"]==["sophomore","junior"]
                    assert fields["eligibility"]["explicit"]["work_authorization_notes"]=="U.S. citizen or permanent resident"
                    assert d["compensation_details"]=="$5,600 stipend" and d["duration"]=="8 weeks"
                    if oid.startswith("nsf-reu-"):
                        assert not d.get("start_date") and d["application"]["application_url"]==etap
                result["terms"]={"stipend":d["compensation_details"],"paid":d["paid"],"eligibility":d["eligibility"],"duration":d["duration"],"application":d["application"]}''')
s=s.replace('                page.screenshot(path=out/(oid+"-date-detail.png"))','''                assert expected in body
                if crisp:
                    assert "Indianapolis, IN" in body and "Bloomington, IN" not in body
                else:
                    assert "U.S. citizen or permanent resident" in body
                    assert "$5,600" in body and "$4,800" not in body and "$6,000-$7,000" not in body
                page.screenshot(path=out/(oid+"-date-detail.png"))''')
s=s.replace('                if oid in ids:','''                assert ids==(["sro-3ec4ea4e"] if crisp else ["nsf-reu-2447670"])
                if oid in ids:''')
s=s.replace('            except Exception as exc:errors[oid]=str(exc)[:800]','''                if oid=="sro-44f176cd":
                    for key, want in [("uiuc_sro","sro-44f176cd"),("nsf_reu","nsf-reu-2447670"),("","nsf-reu-2447670")]:
                        with page.expect_response(lambda r:is_view(r) and ((r.request.post_data_json or {}).get("view",{}).get("source") or "")==key, timeout=60000) as src:
                            page.get_by_role("combobox",name="Source",exact=True).select_option(key)
                        info=src.value.json()
                        assert src.value.ok and [r["opportunity_id"] for r in info["results"]]==[want]
                        assert info["filtered_total"]==1 and not info["has_more"]
                        current=page.locator("#match-card-"+want);expect(current).to_be_visible(timeout=60000)
                        ct=current.inner_text();assert "$5,600" in ct and "2027-02-22" in ct
                        result["source_"+(key or "combined")]={"id":want,"count":1,"card":ct};current.screenshot(path=out/("smu-"+(key or "combined")+".png"))
            except Exception as exc:errors[oid]=str(exc)[:800]''')
s=s.replace('out/"two-sampled-dates.json"','out/"two-verified-host-windows.json"')
s=s.replace('from urllib.parse import quote',
            'from urllib.parse import quote\nfrom verify_berkeley_coverage_card import BerkeleyCoverageCard')
# Berkeley's exact release count was a B12 check. Later academic-route
# checks use the same form without asserting a historical campus count.
academic = sys.argv[2:] == ["academic"]
assert academic or len(sys.argv) == 2
campus_step = "        enter_results(page)"
if not academic:
    campus_step = ('        coverage = BerkeleyCoverageCard(page, receipt, out)\n'
                   '        enter_results(page, before_select=coverage.verify)')
s=s.replace('        enter_results(page)',
            f"        assert 'data-release-sha=\"{sha}\"' in ctx.request.get(site).text()\n"
            '        receipt["frontend_release"] = receipt["backend_release"]\n' + campus_step)
if academic:
    # Before the host eligibility update the generic computer-science profile
    # could see Indiana. The released biomedical/behavioral requirement excludes it.
    s=s.replace('assert ids==(["sro-3ec4ea4e"] if crisp else ["nsf-reu-2447670"])',
                'assert ids==([] if crisp else ["nsf-reu-2447670"])')
    s=s.replace('                assert expected in body', '''                e = fields["eligibility"]
                majors = (["Biomedical science","Behavioral science"] if crisp else
                          ["Mathematics","Statistics","Computer Science","Social science"])
                assert d["eligibility"]["majors"] == e["explicit"]["majors"] == majors
                assert "majors_attribution" not in d
                assert e["quotes"]["majors"]["source_url"].startswith(
                    "https://cancer.iu.edu/" if crisp else "https://www.smu.edu/")
                phrase = "incoming first-year students" if crisp else "two academic routes"
                assert phrase in body and all(major in body for major in majors)
                result["academic_routes"] = {"majors":majors, "source":e["quotes"]["majors"]["source_url"],
                                             "student_summary":d["description_clean"].split("\\n", 1)[0]}
                assert expected in body''')
p.write_text(s)
