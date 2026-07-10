import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import numpy as np
from io import BytesIO
import requests
import base64
import datetime
import json

st.set_page_config(page_title="COD Alert Dashboard", layout="wide", page_icon="💰")

st.title("💰 Dashboard 2 — COD Alert & Analysis")
st.markdown("Monitor Cash on Delivery values, flag high-risk riders, and track liability trends.")

uploaded_file = st.file_uploader("Upload Excel File", type=["xlsx", "xls"])

if uploaded_file:
    xl = pd.ExcelFile(uploaded_file)
    sheets = xl.sheet_names
    st.success(f"✅ File loaded. Sheets found: {', '.join(sheets)}")

    cod_sheet = st.selectbox("Select COD sheet:", sheets,
                              index=next((i for i, s in enumerate(sheets) if "COD" in s.upper()), 0))

    raw = xl.parse(cod_sheet, header=0)

    with st.expander("🔍 Preview raw data"):
        st.dataframe(raw.head(20), use_container_width=True)

    st.markdown("### ⚙️ Column Mapping")
    cols = list(raw.columns)
    col1, col2, col3 = st.columns(3)
    with col1:
        name_col = st.selectbox("Rider Name column:", cols,
                                 index=next((i for i, c in enumerate(cols) if any(k in str(c).upper() for k in ["NAME", "RIDER", "DRIVER"])), 0))
    with col2:
        cod_col = st.selectbox("COD Amount column:", cols,
                                index=next((i for i, c in enumerate(cols) if any(k in str(c).upper() for k in ["COD", "AMOUNT", "VALUE", "CASH"])), min(1, len(cols)-1)))
    with col3:
        date_col = st.selectbox("Date column (optional):", ["None"] + cols)

    threshold = st.slider("🚨 COD Alert Threshold (AED):", min_value=0, max_value=500, value=150, step=10)

    if st.button("🚀 Generate Dashboard"):

        df = raw[[name_col, cod_col] + ([date_col] if date_col != "None" else [])].copy()
        df.columns = ["Rider", "COD"] + (["Date"] if date_col != "None" else [])
        df = df.dropna(subset=["Rider", "COD"])
        df["Rider"] = df["Rider"].astype(str).str.strip()
        df["COD"] = pd.to_numeric(df["COD"], errors="coerce")
        df = df.dropna(subset=["COD"])

        if date_col != "None":
            df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
            df["Month"] = df["Date"].dt.strftime("%b %Y")

        st.markdown("---")

        c1, c2, c3, c4 = st.columns(4)
        flagged = df[df["COD"] > threshold]
        c1.metric("Total Riders", df["Rider"].nunique())
        c2.metric(f"Riders > AED {threshold}", flagged["Rider"].nunique(), delta=None)
        c3.metric("Total COD Liability", f"AED {df['COD'].sum():,.0f}")
        c4.metric("Avg COD per Rider", f"AED {df.groupby('Rider')['COD'].sum().mean():,.0f}")

        st.markdown("---")

        st.subheader(f"🚨 Riders Exceeding AED {threshold} — Flagged Entries")

        if flagged.empty:
            st.success(f"✅ No riders exceed AED {threshold}.")
        else:
            flagged_display = flagged.copy()
            flagged_display["COD"] = flagged_display["COD"].map(lambda x: f"AED {x:,.0f}")
            st.dataframe(flagged_display.reset_index(drop=True), use_container_width=True)

        st.subheader("📊 Per-Rider COD Summary")
        rider_summary = df.groupby("Rider").agg(
            TotalCOD=("COD", "sum"),
            AvgCOD=("COD", "mean"),
            Entries=("COD", "count"),
            BreachCount=("COD", lambda x: (x > threshold).sum())
        ).reset_index().sort_values("TotalCOD", ascending=False)

        rider_summary["BreachRate"] = (rider_summary["BreachCount"] / rider_summary["Entries"] * 100).round(1)

        fig_rider = px.bar(rider_summary.head(20), x="Rider", y="TotalCOD",
                           color="BreachCount",
                           color_continuous_scale="OrRd",
                           title="Top 20 Riders by Total COD Amount",
                           text="TotalCOD",
                           hover_data=["Entries", "BreachCount", "BreachRate"])
        fig_rider.update_traces(texttemplate="AED %{text:,.0f}", textposition="outside")
        fig_rider.add_hline(y=threshold, line_dash="dash", line_color="red",
                            annotation_text=f"Threshold: AED {threshold}")
        fig_rider.update_layout(coloraxis_showscale=False, xaxis_tickangle=-45)
        st.plotly_chart(fig_rider, use_container_width=True)

        st.subheader("🔴 Habitual vs Situational Breach Classification")

        def classify(row):
            if row["BreachCount"] == 0:
                return "✅ No Breach"
            elif row["BreachCount"] == 1:
                return "🟡 Situational (1 breach)"
            elif row["BreachCount"] <= 3:
                return "🟠 Recurring (2–3 breaches)"
            else:
                return "🔴 Habitual (4+ breaches)"

        rider_summary["Classification"] = rider_summary.apply(classify, axis=1)

        col_a, col_b = st.columns(2)
        with col_a:
            class_counts = rider_summary["Classification"].value_counts().reset_index()
            class_counts.columns = ["Classification", "Count"]
            fig_class = px.pie(class_counts, names="Classification", values="Count",
                               title="Breach Classification Distribution",
                               color_discrete_map={
                                   "✅ No Breach": "#2ecc71",
                                   "🟡 Situational (1 breach)": "#f1c40f",
                                   "🟠 Recurring (2–3 breaches)": "#e67e22",
                                   "🔴 Habitual (4+ breaches)": "#e74c3c"
                               })
            st.plotly_chart(fig_class, use_container_width=True)

        with col_b:
            habitual = rider_summary[rider_summary["BreachCount"] >= 4][
                ["Rider", "TotalCOD", "BreachCount", "BreachRate", "Classification"]
            ].copy()
            habitual["TotalCOD"] = habitual["TotalCOD"].map(lambda x: f"AED {x:,.0f}")
            habitual["BreachRate"] = habitual["BreachRate"].map(lambda x: f"{x}%")
            st.markdown("**🔴 Habitual Offenders — Immediate Action Required:**")
            if habitual.empty:
                st.success("No habitual offenders found.")
            else:
                st.dataframe(habitual.reset_index(drop=True), use_container_width=True)

        st.subheader("📋 Recommended Action Tiers")

        def action_tier(row):
            if row["BreachCount"] == 0:
                return "No Action"
            elif row["BreachCount"] == 1:
                return "Verbal Warning"
            elif row["BreachCount"] <= 3:
                return "Written Warning + Coaching"
            else:
                return "Escalate to Management"

        rider_summary["RecommendedAction"] = rider_summary.apply(action_tier, axis=1)
        action_display = rider_summary[rider_summary["BreachCount"] > 0][
            ["Rider", "TotalCOD", "BreachCount", "BreachRate", "Classification", "RecommendedAction"]
        ].copy()
        action_display["TotalCOD"] = action_display["TotalCOD"].map(lambda x: f"AED {x:,.0f}")
        action_display["BreachRate"] = action_display["BreachRate"].map(lambda x: f"{x}%")
        st.dataframe(action_display.reset_index(drop=True), use_container_width=True)

        if "Month" in df.columns:
            st.subheader("📈 Monthly COD Trend")
            monthly = df.groupby("Month").agg(
                TotalCOD=("COD", "sum"),
                AvgCOD=("COD", "mean"),
                Breaches=("COD", lambda x: (x > threshold).sum())
            ).reset_index()

            from plotly.subplots import make_subplots
            fig_trend = make_subplots(specs=[[{"secondary_y": True}]])
            fig_trend.add_trace(go.Bar(x=monthly["Month"], y=monthly["TotalCOD"],
                                       name="Total COD", marker_color="#3498db"), secondary_y=False)
            fig_trend.add_trace(go.Scatter(x=monthly["Month"], y=monthly["Breaches"],
                                           name=f"Breaches > {threshold}", mode="lines+markers",
                                           line=dict(color="red", width=2)), secondary_y=True)
            fig_trend.update_layout(title="Monthly COD Liability & Breach Count")
            fig_trend.update_yaxes(title_text="Total COD (AED)", secondary_y=False)
            fig_trend.update_yaxes(title_text="Number of Breaches", secondary_y=True)
            st.plotly_chart(fig_trend, use_container_width=True)

        st.subheader("📦 COD Value Distribution")
        fig_hist = px.histogram(df, x="COD", nbins=30,
                                title="Distribution of COD Values",
                                color_discrete_sequence=["#3498db"])
        fig_hist.add_vline(x=threshold, line_dash="dash", line_color="red",
                           annotation_text=f"Threshold: AED {threshold}")
        st.plotly_chart(fig_hist, use_container_width=True)

        # Build email content and save to session_state
        flagged_riders = action_display[action_display["RecommendedAction"] != "No Action"].copy() if not action_display.empty else pd.DataFrame()
        rider_rows = ""
        for _, row in flagged_riders.iterrows():
            rider_rows += f"<tr><td style='padding:8px;border:1px solid #ddd;'>{row['Rider']}</td><td style='padding:8px;border:1px solid #ddd;text-align:center;'>{row['TotalCOD']}</td><td style='padding:8px;border:1px solid #ddd;text-align:center;'>{row['BreachCount']}</td><td style='padding:8px;border:1px solid #ddd;'>{row['Classification']}</td><td style='padding:8px;border:1px solid #ddd;'>{row['RecommendedAction']}</td></tr>"

        email_html = f"""<html><body style="font-family:Arial,sans-serif;color:#212121;">
          <div style="background:#00897B;padding:20px;border-radius:6px 6px 0 0;">
            <h2 style="color:white;margin:0;">⚠️ COD Alert — Automated Notification</h2>
            <p style="color:#B2DFDB;margin:4px 0 0;">Generated: {datetime.datetime.now().strftime('%d %b %Y, %I:%M %p')}</p>
          </div>
          <div style="background:#f9f9f9;padding:20px;border:1px solid #ddd;border-top:none;">
            <p>The following riders have COD values exceeding <strong>AED {threshold}</strong>:</p>
            <table style="border-collapse:collapse;width:100%;margin:16px 0;">
              <tr style="background:#00897B;color:white;">
                <th style="padding:10px;text-align:left;">Rider</th>
                <th style="padding:10px;text-align:center;">Total COD</th>
                <th style="padding:10px;text-align:center;">Breaches</th>
                <th style="padding:10px;text-align:left;">Classification</th>
                <th style="padding:10px;text-align:left;">Recommended Action</th>
              </tr>{rider_rows}
            </table>
            <p style="color:#757575;font-size:13px;">Flagged riders: <strong>{len(flagged_riders)}</strong> | Threshold: <strong>AED {threshold}</strong></p>
          </div>
        </body></html>"""

        # Save to session_state - persists across Streamlit reruns caused by form submit
        st.session_state.dash2_data = {
            "action_display": action_display,
            "email_html":     email_html,
            "flagged_count":  len(flagged_riders),
            "threshold":      threshold,
            "rider_summary":  rider_summary,
            "flagged":        flagged,
        }

    # EMAIL TRIGGER + EXPORT - outside button block so they survive reruns
    if "dash2_data" in st.session_state:
        d = st.session_state.dash2_data

        st.markdown("---")
        st.subheader("📧 Automated Email Alert Trigger")
        st.info(f"This will send an alert email listing all riders with COD > AED {d['threshold']}, their breach count, and recommended action.")

        st.subheader("📄 Email Preview")
        st.components.v1.html(d["email_html"], height=380, scrolling=True)

        st.markdown("**📬 Send this alert:**")
        with st.expander("ℹ️ How to get a free SendGrid API Key (one-time setup)"):
            st.markdown("""
            1. Go to [sendgrid.com](https://sendgrid.com) → **Start for Free**
            2. Sign up with any email
            3. After login → **Settings → API Keys → Create API Key**
            4. Name it "noon Dashboard" → **Full Access** → Create
            5. Copy the key (starts with `SG.`) and paste below
            6. Also verify your sender email: **Settings → Sender Authentication → Single Sender Verify**
            """)

        if "email_status" not in st.session_state:
            st.session_state.email_status = None
            st.session_state.email_msg    = ""

        with st.form("email_form"):
            col1, col2 = st.columns(2)
            with col1:
                sg_api_key   = st.text_input("SendGrid API Key:", placeholder="SG.xxxxxxxx", type="password")
                sender_email = st.text_input("Your verified sender email:", placeholder="yourname@gmail.com",
                                             help="Must be verified in SendGrid Sender Authentication")
            with col2:
                recipient_email = st.text_input("Send alert to:", placeholder="manager@noon.com")
                cc_email        = st.text_input("CC (optional):", placeholder="hr@noon.com")
            email_subject = st.text_input("Subject:",
                value=f"⚠️ COD Alert — {d['flagged_count']} Riders Exceed AED {d['threshold']} | {datetime.date.today().strftime('%d %b %Y')}")
            send_clicked = st.form_submit_button("📤 Send Alert Email", type="primary", use_container_width=True)

        if send_clicked:
            if not sg_api_key or not sender_email or not recipient_email:
                st.session_state.email_status = "error"
                st.session_state.email_msg    = "❌ Please fill in the SendGrid API Key, sender email, and recipient email."
            else:
                report_bytes = BytesIO()
                with pd.ExcelWriter(report_bytes, engine="openpyxl") as w:
                    d["action_display"].to_excel(w, sheet_name="COD Alert Report", index=False)
                attachment_b64 = base64.b64encode(report_bytes.getvalue()).decode()

                to_list = [{"email": recipient_email}]
                if cc_email:
                    to_list.append({"email": cc_email})

                payload = {
                    "personalizations": [{"to": to_list}],
                    "from":             {"email": sender_email},
                    "subject":          email_subject,
                    "content":          [{"type": "text/html", "value": d["email_html"]}],
                    "attachments":      [{
                        "content":  attachment_b64,
                        "type":     "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        "filename": f"COD_Alert_{datetime.date.today()}.xlsx"
                    }]
                }

                try:
                    body_bytes = json.dumps(payload, ensure_ascii=True).encode("ascii")
                    response = requests.post(
                        "https://api.sendgrid.com/v3/mail/send",
                        headers={
                            "Authorization": "Bearer " + sg_api_key,
                            "Content-Type": "application/json",
                            "Content-Length": str(len(body_bytes)),
                        },
                        data=body_bytes,
                        timeout=15
                    )
                    if response.status_code in [200, 202]:
                        st.session_state.email_status = "success"
                        st.session_state.email_msg    = (
                            f"✅ Alert sent to **{recipient_email}**" +
                            (f" and CC'd **{cc_email}**" if cc_email else "") +
                            " — Excel report attached!"
                        )
                    else:
                        st.session_state.email_status = "error"
                        st.session_state.email_msg    = f"❌ SendGrid error {response.status_code}: {response.text}"
                except Exception as e:
                    st.session_state.email_status = "error"
                    st.session_state.email_msg    = f"❌ Request failed: {str(e)}"

        if st.session_state.email_status == "success":
            st.success(st.session_state.email_msg)
        elif st.session_state.email_status == "error":
            st.error(st.session_state.email_msg)

        st.subheader("⬇️ Export Report")
        out = BytesIO()
        with pd.ExcelWriter(out, engine="openpyxl") as writer:
            d["rider_summary"].to_excel(writer, sheet_name="Rider Summary", index=False)
            if not d["flagged"].empty:
                d["flagged"].to_excel(writer, sheet_name="Flagged Entries", index=False)
            d["action_display"].to_excel(writer, sheet_name="Action Plan", index=False)
        st.download_button("Download Excel Report", out.getvalue(),
                           file_name="cod_alert_report.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

else:
    st.info("☝️ Please upload the noon operational Excel file to get started.")
    with st.expander("ℹ️ Expected Data Format"):
        st.markdown("""
        **COD Sheet:**
        - Column: Rider / Employee Name
        - Column: COD Amount (numeric, in AED)
        - Column (optional): Date of transaction

        The dashboard will flag all entries exceeding the threshold (default AED 150) and classify riders by breach frequency.
        """)
