import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import numpy as np
from io import BytesIO
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
import datetime

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

        # ── KPI Cards ───────────────────────────────────────────────────
        c1, c2, c3, c4 = st.columns(4)
        flagged = df[df["COD"] > threshold]
        c1.metric("Total Riders", df["Rider"].nunique())
        c2.metric(f"Riders > AED {threshold}", flagged["Rider"].nunique(), delta=None)
        c3.metric("Total COD Liability", f"AED {df['COD'].sum():,.0f}")
        c4.metric("Avg COD per Rider", f"AED {df.groupby('Rider')['COD'].sum().mean():,.0f}")

        st.markdown("---")

        # ── SECTION 1: Flagged Riders ────────────────────────────────────
        st.subheader(f"🚨 Riders Exceeding AED {threshold} — Flagged Entries")

        if flagged.empty:
            st.success(f"✅ No riders exceed AED {threshold}.")
        else:
            flagged_display = flagged.copy()
            flagged_display["COD"] = flagged_display["COD"].map(lambda x: f"AED {x:,.0f}")
            st.dataframe(flagged_display.reset_index(drop=True), use_container_width=True)

        # ── SECTION 2: Per-Rider COD Summary ─────────────────────────────
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

        # ── SECTION 3: Habitual vs Situational Classification ────────────
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

        # ── SECTION 4: Action Tier Recommendation ────────────────────────
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

        # ── SECTION 5: Monthly COD Trend ─────────────────────────────────
        if "Month" in df.columns:
            st.subheader("📈 Monthly COD Trend")
            monthly = df.groupby("Month").agg(
                TotalCOD=("COD", "sum"),
                AvgCOD=("COD", "mean"),
                Breaches=("COD", lambda x: (x > threshold).sum())
            ).reset_index()

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

        # ── SECTION 6: COD Distribution ──────────────────────────────────
        st.subheader("📦 COD Value Distribution")
        fig_hist = px.histogram(df, x="COD", nbins=30,
                                title="Distribution of COD Values",
                                color_discrete_sequence=["#3498db"])
        fig_hist.add_vline(x=threshold, line_dash="dash", line_color="red",
                           annotation_text=f"Threshold: AED {threshold}")
        st.plotly_chart(fig_hist, use_container_width=True)

        # ── SECTION 7: Email Trigger ──────────────────────────────────────
        st.markdown("---")
        st.subheader("📧 Automated Email Alert Trigger")
        st.info(f"This will send an alert email listing all riders with COD > AED {threshold}, their breach count, and recommended action.")

        with st.expander("⚙️ Email Configuration", expanded=True):
            col1, col2 = st.columns(2)
            with col1:
                sender_email    = st.text_input("Your Gmail address:", placeholder="yourname@gmail.com")
                sender_password = st.text_input("Gmail App Password:", type="password",
                                                help="Use a Gmail App Password (not your regular password). Go to Google Account → Security → App Passwords.")
            with col2:
                recipient_email = st.text_input("Send alert to:", placeholder="manager@noon.com")
                cc_email        = st.text_input("CC (optional):", placeholder="hr@noon.com")
                email_subject   = st.text_input("Email subject:",
                                                value=f"⚠️ COD Alert — {len(action_display)} Riders Exceed AED {threshold} | {datetime.date.today().strftime('%d %b %Y')}")

        # Email preview
        flagged_riders = action_display[action_display["RecommendedAction"] != "No Action"].copy() if not action_display.empty else pd.DataFrame()

        rider_rows = ""
        if not flagged_riders.empty:
            for _, row in flagged_riders.iterrows():
                rider_rows += f"""
                <tr>
                  <td style="padding:8px;border:1px solid #ddd;">{row['Rider']}</td>
                  <td style="padding:8px;border:1px solid #ddd;text-align:center;">{row['TotalCOD']}</td>
                  <td style="padding:8px;border:1px solid #ddd;text-align:center;">{row['BreachCount']}</td>
                  <td style="padding:8px;border:1px solid #ddd;text-align:center;">{row['Classification']}</td>
                  <td style="padding:8px;border:1px solid #ddd;">{row['RecommendedAction']}</td>
                </tr>"""

        email_html = f"""
        <html><body style="font-family:Arial,sans-serif;color:#212121;">
          <div style="background:#00897B;padding:20px;border-radius:6px 6px 0 0;">
            <h2 style="color:white;margin:0;">⚠️ COD Alert — Automated Notification</h2>
            <p style="color:#B2DFDB;margin:4px 0 0;">Generated: {datetime.datetime.now().strftime('%d %b %Y, %I:%M %p')}</p>
          </div>
          <div style="background:#f9f9f9;padding:20px;border:1px solid #ddd;border-top:none;">
            <p>This is an automated alert from the <strong>noon Fleet Operations Dashboard</strong>.</p>
            <p>The following riders have COD values exceeding <strong>AED {threshold}</strong> and require attention:</p>
            <table style="border-collapse:collapse;width:100%;margin:16px 0;">
              <tr style="background:#00897B;color:white;">
                <th style="padding:10px;text-align:left;">Rider</th>
                <th style="padding:10px;text-align:center;">Total COD</th>
                <th style="padding:10px;text-align:center;">Breaches</th>
                <th style="padding:10px;text-align:center;">Classification</th>
                <th style="padding:10px;text-align:left;">Recommended Action</th>
              </tr>
              {rider_rows}
            </table>
            <p style="color:#757575;font-size:13px;">
              Total flagged riders: <strong>{len(flagged_riders)}</strong> &nbsp;|&nbsp;
              Threshold: <strong>AED {threshold}</strong> &nbsp;|&nbsp;
              Generated by: noon Fleet Operations Intelligence Dashboard
            </p>
          </div>
          <div style="background:#E0F2F1;padding:12px 20px;border:1px solid #ddd;border-top:none;border-radius:0 0 6px 6px;">
            <p style="margin:0;font-size:12px;color:#00897B;">This is an automated message. Please do not reply to this email.</p>
          </div>
        </body></html>"""

        st.subheader("📄 Email Preview")
        st.components.v1.html(email_html, height=420, scrolling=True)

        col_send, col_test = st.columns([1, 3])
        with col_send:
            send_clicked = st.button("📤 Send Alert Email", type="primary", use_container_width=True)

        if send_clicked:
            if not sender_email or not sender_password or not recipient_email:
                st.error("Please fill in sender email, app password, and recipient email.")
            else:
                try:
                    msg = MIMEMultipart("alternative")
                    msg["Subject"] = email_subject
                    msg["From"]    = sender_email
                    msg["To"]      = recipient_email
                    if cc_email:
                        msg["Cc"] = cc_email

                    msg.attach(MIMEText(email_html, "html"))

                    # Attach the report as Excel
                    report_bytes = BytesIO()
                    with pd.ExcelWriter(report_bytes, engine="openpyxl") as w:
                        action_display.to_excel(w, sheet_name="COD Alert Report", index=False)
                    attachment = MIMEBase("application", "octet-stream")
                    attachment.set_payload(report_bytes.getvalue())
                    encoders.encode_base64(attachment)
                    attachment.add_header("Content-Disposition",
                                          f"attachment; filename=COD_Alert_{datetime.date.today()}.xlsx")
                    msg.attach(attachment)

                    recipients = [recipient_email] + ([cc_email] if cc_email else [])
                    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
                        server.login(sender_email, sender_password)
                        server.sendmail(sender_email, recipients, msg.as_string())

                    st.success(f"✅ Alert email sent to {recipient_email}" + (f" and CC'd to {cc_email}" if cc_email else "") + " with Excel report attached!")
                except smtplib.SMTPAuthenticationError:
                    st.error("❌ Authentication failed. Make sure you're using a Gmail App Password, not your regular password.")
                except Exception as e:
                    st.error(f"❌ Failed to send email: {str(e)}")

        with st.expander("ℹ️ How to get a Gmail App Password"):
            st.markdown("""
            1. Go to [myaccount.google.com](https://myaccount.google.com)
            2. Click **Security** → **2-Step Verification** (must be enabled)
            3. Scroll down → **App Passwords**
            4. Select app: **Mail** | Select device: **Other** → enter "noon Dashboard"
            5. Copy the 16-character password and paste it above
            """)

        # ── Export ───────────────────────────────────────────────────────
        st.subheader("⬇️ Export Report")
        out = BytesIO()
        with pd.ExcelWriter(out, engine="openpyxl") as writer:
            rider_summary.to_excel(writer, sheet_name="Rider Summary", index=False)
            if not flagged.empty:
                flagged.to_excel(writer, sheet_name="Flagged Entries", index=False)
            action_display.to_excel(writer, sheet_name="Action Plan", index=False)
        st.download_button("Download Excel Report", out.getvalue(),
                           file_name="cod_alert_report.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

else:
    st.info("👆 Please upload the noon operational Excel file to get started.")
    with st.expander("ℹ️ Expected Data Format"):
        st.markdown("""
        **COD Sheet:**
        - Column: Rider / Employee Name
        - Column: COD Amount (numeric, in AED)
        - Column (optional): Date of transaction

        The dashboard will flag all entries exceeding the threshold (default AED 150) and classify riders by breach frequency.
        """)
