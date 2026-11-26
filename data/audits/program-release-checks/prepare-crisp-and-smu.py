from pathlib import Path
import subprocess,sys
p=Path("data/audits/verify_m23_manual_20261126.py")
sha=sys.argv[1]
assert len(sha)==40 and set(sha)<=set("0123456789abcdef")
s=subprocess.check_output(["git","show","76afc3cca:"+str(p)],text=True)
s=s.replace("743e6fa6e6b8d56c39e5c2eb29a92a4fcdc16d7f",sha)
s=s.replace('    ("sro-44f176cd","Advancing Data Science in the Public Interest",["https://researchops.web.illinois.edu/opportunity/reu-advancing-data-science-public-interest",etap]),','''    ("sro-44f176cd","Advancing Data Science in the Public Interest",["https://researchops.web.illinois.edu/opportunity/reu-advancing-data-science-public-interest",etap]),''')
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
p.write_text(s)
