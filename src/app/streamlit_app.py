"""
Streamlit MVP — Opportunity Filter Engine
Run with: streamlit run src/app/streamlit_app.py
"""

import streamlit as st
import json
import sys
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path
from collections import Counter

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.matcher.ranker import rank_all, MatchResult


# ────────────────────────────────────────
# Helper functions (must be defined first)
# ────────────────────────────────────────

def _load_opportunities() -> list:
    """Load opportunities from processed data or fall back to examples."""
    processed_path = PROJECT_ROOT / "data" / "processed" / "opportunities.json"
    if processed_path.exists():
        with open(processed_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if data:
                return data

    examples_path = PROJECT_ROOT / "examples" / "sample_opportunities.json"
    if examples_path.exists():
        with open(examples_path, "r", encoding="utf-8") as f:
            return json.load(f)

    return []


def _intl_badge(value: str) -> str:
    """Return a colored badge for international-friendly status."""
    if value == "yes":
        return ":green[Intl OK]"
    elif value == "no":
        return ":red[US Only]"
    else:
        return ":orange[Intl Unknown]"


def _paid_badge(value: str) -> str:
    if value == "yes":
        return ":green[Paid]"
    elif value == "stipend":
        return ":blue[Stipend]"
    elif value == "no":
        return ":gray[Unpaid]"
    else:
        return ":gray[Pay Unknown]"


def _bucket_icon(bucket: str) -> str:
    return {
        "high_priority": "\U0001f7e2",
        "good_match": "\U0001f535",
        "reach": "\U0001f7e1",
        "low_fit": "\U0001f534",
    }.get(bucket, "\u2b1c")


def _bucket_label(bucket: str) -> str:
    return {
        "high_priority": "High Priority",
        "good_match": "Good Match",
        "reach": "Reach",
        "low_fit": "Low Fit",
    }.get(bucket, "Unknown")


def _render_result_card(opp: dict, result: MatchResult):
    """Render a single opportunity result card."""
    icon = _bucket_icon(result.bucket)
    label = _bucket_label(result.bucket)
    intl = opp.get("eligibility", {}).get("international_friendly", "unknown")
    paid = opp.get("paid", "unknown")

    with st.expander(
        f"{icon} **{opp.get('title', 'Unknown')}** — {result.final_score:.0f}/100 ({label})",
        expanded=(result.bucket == "high_priority"),
    ):
        # Score metrics row
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Eligibility", f"{result.eligibility_score:.0f}")
        c2.metric("Readiness", f"{result.readiness_score:.0f}")
        c3.metric("Upside", f"{result.upside_score:.0f}")
        c4.metric("Final", f"{result.final_score:.0f}")

        # Info row with badges
        org = opp.get("organization", "")
        loc = opp.get("location", "")
        opp_type = opp.get("opportunity_type", "")
        deadline = opp.get("deadline") or "Not specified"
        source = opp.get("source", "")

        st.markdown(
            f"**Org:** {org} &middot; **Location:** {loc} &middot; "
            f"**Type:** {opp_type} &middot; {_paid_badge(paid)} &middot; "
            f"{_intl_badge(intl)} &middot; **Deadline:** {deadline} &middot; "
            f"**Source:** {source}"
        )

        if opp.get("url"):
            st.markdown(f"[\U0001f517 View Posting]({opp['url']})")

        # Description
        desc = opp.get("description_clean", "") or opp.get("description_raw", "")
        if desc and len(desc) > 10:
            clean = desc[:300].strip()
            if len(desc) > 300:
                clean += "..."
            st.caption(clean)

        # Fit / Gap / Next Steps in columns
        col_left, col_right = st.columns(2)

        with col_left:
            if result.reasons_fit:
                st.markdown("**\u2705 Why it fits:**")
                for reason in result.reasons_fit[:4]:
                    st.markdown(f"- {reason}")

        with col_right:
            if result.reasons_gap:
                st.markdown("**\u26a0\ufe0f Potential concerns:**")
                for gap in result.reasons_gap[:4]:
                    st.markdown(f"- {gap}")

        if result.next_steps:
            st.markdown("**\U0001f4cb Next steps:**")
            for i, step in enumerate(result.next_steps, 1):
                st.markdown(f"{i}. {step}")

        effort = opp.get("application", {}).get("application_effort", "unknown")
        st.caption(f"Application effort: {effort}")


def _render_dashboard(opportunities: list):
    """Render the Dashboard tab with charts and stats."""
    st.subheader("Overview Stats")

    # Key metrics
    total = len(opportunities)
    active = sum(1 for o in opportunities if o.get("metadata", {}).get("is_active", True))
    paid_count = sum(1 for o in opportunities if o.get("paid") in ("yes", "stipend"))
    intl_count = sum(1 for o in opportunities if o.get("eligibility", {}).get("international_friendly") == "yes")

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total Opportunities", total)
    m2.metric("Active", active)
    m3.metric("Paid / Stipend", paid_count)
    m4.metric("International Friendly", intl_count)

    st.divider()

    # Charts side by side
    col_left, col_right = st.columns(2)

    with col_left:
        st.subheader("By Type")
        type_counts = Counter(o.get("opportunity_type", "unknown") for o in opportunities)
        type_df = pd.DataFrame(
            list(type_counts.items()),
            columns=["Type", "Count"]
        ).sort_values("Count", ascending=False)
        st.bar_chart(type_df.set_index("Type"))

    with col_right:
        st.subheader("By Research Area / Department")
        # Collect keywords and departments
        area_counter = Counter()
        for opp in opportunities:
            keywords = opp.get("keywords", [])
            dept = opp.get("department", "")
            if keywords:
                for kw in keywords:
                    if kw.strip():
                        area_counter[kw.strip()] += 1
            elif dept:
                area_counter[dept] += 1
            else:
                area_counter["Unspecified"] += 1

        top_areas = area_counter.most_common(12)
        area_df = pd.DataFrame(top_areas, columns=["Area", "Count"])
        st.bar_chart(area_df.set_index("Area"))

    st.divider()

    # Source breakdown
    st.subheader("By Source")
    source_counts = Counter(o.get("source", "unknown") for o in opportunities)
    source_df = pd.DataFrame(
        list(source_counts.items()),
        columns=["Source", "Count"]
    ).sort_values("Count", ascending=False)
    st.bar_chart(source_df.set_index("Source"))

    st.divider()

    # International / Paid breakdown
    col_a, col_b = st.columns(2)

    with col_a:
        st.subheader("International Eligibility")
        intl_counts = Counter(
            o.get("eligibility", {}).get("international_friendly", "unknown")
            for o in opportunities
        )
        intl_df = pd.DataFrame(
            [(k, v) for k, v in intl_counts.items()],
            columns=["Status", "Count"]
        )
        st.bar_chart(intl_df.set_index("Status"))

    with col_b:
        st.subheader("Paid Status")
        paid_counts = Counter(o.get("paid", "unknown") for o in opportunities)
        paid_df = pd.DataFrame(
            [(k, v) for k, v in paid_counts.items()],
            columns=["Status", "Count"]
        )
        st.bar_chart(paid_df.set_index("Status"))

    st.divider()

    # Deadline timeline (upcoming 3 months)
    st.subheader("Upcoming Deadlines (Next 3 Months)")
    today = datetime.now()
    three_months = today + timedelta(days=90)

    deadline_opps = []
    for opp in opportunities:
        deadline_str = opp.get("deadline")
        if not deadline_str:
            continue
        # Try parsing various date formats
        parsed = None
        for fmt in ["%Y-%m-%d", "%B %d, %Y", "%b %d, %Y", "%m/%d/%Y", "%B %d %Y"]:
            try:
                parsed = datetime.strptime(deadline_str.strip(), fmt)
                break
            except ValueError:
                continue
        if parsed and today <= parsed <= three_months:
            deadline_opps.append({
                "Title": opp.get("title", "")[:50],
                "Deadline": parsed.strftime("%Y-%m-%d"),
                "Type": opp.get("opportunity_type", "unknown"),
                "Paid": opp.get("paid", "unknown"),
            })

    if deadline_opps:
        deadline_df = pd.DataFrame(deadline_opps).sort_values("Deadline")
        st.dataframe(deadline_df, use_container_width=True, hide_index=True)

        # Bar chart of deadlines by week
        deadline_df["Week"] = pd.to_datetime(deadline_df["Deadline"]).dt.isocalendar().week
        week_counts = deadline_df.groupby("Week").size().reset_index(name="Count")
        week_counts["Week"] = "Week " + week_counts["Week"].astype(str)
        st.bar_chart(week_counts.set_index("Week"))
    else:
        st.info("No opportunities with parseable deadlines in the next 3 months.")


def _render_about():
    """Render the About tab."""
    st.subheader("About Opportunity Filter Engine")

    st.markdown("""
**Opportunity Filter Engine** is a personalized research and internship matching tool
built for UIUC undergraduates. It helps students discover opportunities that match
their skills, interests, and eligibility.

**How it works:**
1. **Data Collection** - Aggregates opportunities from multiple sources:
   - UIUC Office of Undergraduate Research (RSS feed)
   - UIUC Summer Research Opportunities Database (web scraping)
   - Manually curated opportunities
2. **Smart Matching** - A three-layer scoring engine evaluates each opportunity:
   - **Eligibility (45%)** - Year, major, skills, citizenship match
   - **Readiness (35%)** - Resume, experience, coursework preparedness
   - **Upside (20%)** - Compensation, prestige, mentorship potential
3. **Personalized Results** - Opportunities are ranked and categorized into
   High Priority, Good Match, Reach, and Low Fit buckets

**Key Features:**
- International student friendly filtering
- Deep scraping for richer opportunity data
- LLM-enhanced auto-tagging for missing fields
- Rule-based fallback when no API key is available

**Tech Stack:** Python, Streamlit, BeautifulSoup, pandas

**Source:** Built as an educational project at UIUC.
    """)

    st.divider()
    st.caption("V1 MVP — Opportunity Filter Engine")


# ────────────────────────────────────────
# Page Config
# ────────────────────────────────────────

st.set_page_config(
    page_title="Opportunity Filter Engine",
    page_icon="\U0001f50d",
    layout="wide",
)

st.title("\U0001f50d Opportunity Filter Engine")
st.markdown("*Find research & summer programs that actually match your profile*")


# ────────────────────────────────────────
# Sidebar: Profile Input
# ────────────────────────────────────────

with st.sidebar:
    st.header("\U0001f464 Your Profile")

    year = st.selectbox("Year", ["freshman", "sophomore", "junior", "senior"])
    major = st.text_input("Major", value="ECE")

    secondary = st.multiselect(
        "Secondary Interests",
        ["CS", "ECE", "STAT", "Data Science", "IS", "Math", "Physics"],
        default=["CS", "Data Science"],
    )

    international = st.checkbox("International Student", value=True)

    seeking = st.multiselect(
        "What are you looking for?",
        ["research", "summer_program", "internship", "fellowship", "event"],
        default=["research", "summer_program"],
    )

    skills = st.multiselect(
        "Technical Skills",
        ["Python", "Java", "C++", "C", "JavaScript", "R", "MATLAB",
         "PyTorch", "TensorFlow", "pandas", "SQL", "Git", "Linux",
         "React", "Flask", "FastAPI", "Docker", "OpenCV"],
        default=["Python", "Java", "C++", "pandas"],
    )

    coursework = st.text_input(
        "Relevant Coursework (comma-separated)",
        value="CS 124, ECE 120, STAT 107",
    )

    experience = st.select_slider(
        "Experience Level",
        options=["none", "beginner", "some", "strong"],
        value="beginner",
    )

    resume_ready = st.checkbox("Resume Ready", value=True)
    can_cold_email = st.checkbox("Comfortable Cold Emailing", value=True)

    st.divider()
    st.subheader("\u2699\ufe0f Filters")

    exclude_restricted = st.checkbox(
        "Hide citizenship-restricted opportunities",
        value=True,
    )

    show_paid_only = st.checkbox("Show paid opportunities only", value=False)

    sort_by = st.selectbox(
        "Sort by",
        ["Match Score (high to low)", "Deadline (soonest)", "Organization (A-Z)"],
        index=0,
    )

    st.divider()
    st.caption("V1 MVP \u2014 Opportunity Filter Engine")


# ────────────────────────────────────────
# Build Profile
# ────────────────────────────────────────

profile = {
    "name": "",
    "school": "UIUC",
    "year": year,
    "major": major,
    "secondary_interests": secondary,
    "international_student": international,
    "seeking_type": seeking,
    "desired_fields": [],
    "hard_skills": skills,
    "coursework": [c.strip() for c in coursework.split(",") if c.strip()],
    "experience_level": experience,
    "resume_ready": resume_ready,
    "linkedin_ready": False,
    "can_cold_email": can_cold_email,
    "preferred_location": "on-campus" if international else "either",
    "time_availability": "summer",
    "preferences": {
        "min_match_threshold": 25,
        "show_reach_opportunities": True,
        "prioritize_paid": True,
        "exclude_citizenship_restricted": exclude_restricted,
    },
}


# ────────────────────────────────────────
# Load and Match (auto-run)
# ────────────────────────────────────────

opportunities = _load_opportunities()

if not opportunities:
    st.warning("No opportunity data found. Run `manual_importer.py` or `uiuc_our_rss.py --save` first.")
    st.stop()

# Data stats in sidebar
with st.sidebar:
    source_counts = Counter(o.get("source", "unknown") for o in opportunities)
    st.markdown(f"**\U0001f4ca Data:** {len(opportunities)} opportunities")
    for src, cnt in sorted(source_counts.items()):
        st.caption(f"  {src}: {cnt}")

# Run matching
results = rank_all(profile, opportunities)

# Apply additional filters
if show_paid_only:
    paid_ids = {o["id"] for o in opportunities if o.get("paid") in ("yes", "stipend")}
    results = [r for r in results if r.opportunity_id in paid_ids]

if seeking:
    type_ids = {o["id"] for o in opportunities if o.get("opportunity_type") in seeking}
    results = [r for r in results if r.opportunity_id in type_ids]

# Apply sorting
if sort_by == "Deadline (soonest)":
    def _deadline_key(r):
        opp = next((o for o in opportunities if o["id"] == r.opportunity_id), {})
        d = opp.get("deadline") or ""
        return (0 if d else 1, d, -r.final_score)
    results.sort(key=_deadline_key)
elif sort_by == "Organization (A-Z)":
    def _org_key(r):
        opp = next((o for o in opportunities if o["id"] == r.opportunity_id), {})
        return (opp.get("organization", "ZZZ"), -r.final_score)
    results.sort(key=_org_key)
# Default: already sorted by final_score from rank_all


# ────────────────────────────────────────
# Display Results with Dashboard and About tabs
# ────────────────────────────────────────

# Summary metrics
high = [r for r in results if r.bucket == "high_priority"]
good = [r for r in results if r.bucket == "good_match"]
reach = [r for r in results if r.bucket == "reach"]
low = [r for r in results if r.bucket == "low_fit"]

# Main navigation tabs
tab_matches, tab_dashboard, tab_about = st.tabs([
    "\U0001f50d Matches",
    "\U0001f4ca Dashboard",
    "\u2139\ufe0f About",
])

with tab_matches:
    if not results:
        st.info("No matching opportunities found with current filters. Try adjusting your profile or filters.")
    else:
        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("Total Shown", len(results))
        m2.metric("\U0001f7e2 High Priority", len(high))
        m3.metric("\U0001f535 Good Match", len(good))
        m4.metric("\U0001f7e1 Reach", len(reach))
        m5.metric("\U0001f534 Low Fit", len(low))

        st.divider()

        # Tab-based display
        sub_all, sub_high, sub_good, sub_reach = st.tabs([
            f"All ({len(results)})",
            f"\U0001f7e2 High Priority ({len(high)})",
            f"\U0001f535 Good Match ({len(good)})",
            f"\U0001f7e1 Reach ({len(reach)})",
        ])

        def _render_list(result_list):
            if not result_list:
                st.info("No opportunities in this category.")
                return
            for result in result_list:
                opp = next((o for o in opportunities if o["id"] == result.opportunity_id), {})
                _render_result_card(opp, result)

        with sub_all:
            _render_list(results)

        with sub_high:
            _render_list(high)

        with sub_good:
            _render_list(good)

        with sub_reach:
            _render_list(reach)

with tab_dashboard:
    _render_dashboard(opportunities)

with tab_about:
    _render_about()
