import json
import os
import time
from datetime import datetime

import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from huggingface_hub import InferenceClient
from langchain_core.prompts import ChatPromptTemplate

load_dotenv()

st.set_page_config(page_title="AI Expense Categorizer", layout="wide")

HF_TOKEN = os.getenv("HUGGINGFACE_API_TOKEN")
if not HF_TOKEN:
    st.error("Add HUGGINGFACE_API_TOKEN to your .env file")
    st.stop()

CATEGORIES = [
    "Travel", "Meals", "Software", "Utilities", "Office Supplies",
    "Marketing", "Services", "Rent", "Equipment", "Insurance",
    "Taxes", "Miscellaneous", "Uncategorized"
]

def categorize_expense(date, amount, description):
    """Categorize one expense using AI"""

    prompt = ChatPromptTemplate.from_messages([
        ("human", """Categorize this expense:

            Date: {date}
            Amount: ${amount}
            Description: {description}

            Available categories: {categories}

            Return ONLY JSON:
            {{"category": "<category>", "confidence": "<high|medium|low>", "is_anomaly": <true|false>, "notes": "<brief>"}}""")
                ])
                
    formatted = prompt.format_messages(
        date=date,
        amount=amount,
        description=description,
        categories=", ".join(CATEGORIES)
    )
    
    client = InferenceClient(token=HF_TOKEN)
    response = client.chat_completion(
        model="mistralai/Mistral-7B-Instruct-v0.2",
        messages=[{"role": "user", "content": formatted[0].content}],
        max_tokens=300,
        temperature=0.1,
    )
    
    text = response.choices[0].message.content.strip()
    
    # Parsing JSON
    try:
        if "```" in text:
            text = text.split("```")[1].replace("json", "").strip()
        start, end = text.find("{"), text.rfind("}") + 1
        if start != -1 and end > start:
            data = json.loads(text[start:end])
            return {
                "category": data.get("category", "Uncategorized"),
                "confidence": data.get("confidence", "medium"),
                "is_anomaly": data.get("is_anomaly", False),
                "notes": data.get("notes", "")
            }
    except:
        pass
    
    return {"category": "Uncategorized", "confidence": "low", "is_anomaly": False, "notes": "Parse error"}


def main():
    st.title("AI Expense Categorizer")
    
    uploaded = st.file_uploader("Upload CSV file", type=["csv"])
    
    if not uploaded:
        st.info("Upload a CSV file to start")
        return
    
    try:
        df = pd.read_csv(uploaded)
        df.columns = df.columns.str.lower().str.strip()
        
        required = ["date", "amount", "description"]
        missing = [c for c in required if c not in df.columns]
        if missing:
            st.error(f"Missing: {', '.join(missing)}")
            return
        
        df["amount"] = pd.to_numeric(df["amount"].astype(str).str.replace(r"[\$,]", "", regex=True), errors="coerce")
        df = df.dropna(subset=["amount"])
        df = df[df["amount"] > 0].reset_index(drop=True)
        
        st.success(f"{len(df)} transactions loaded")
        
    except Exception as e:
        st.error(f"Error: {e}")
        return
    
    if st.button("Categorize with AI", type="primary", use_container_width=True):
        results = []
        bar = st.progress(0)
        status = st.empty()
        
        for i, row in df.iterrows():
            status.text(f"Processing {i+1}/{len(df)}: {row['description'][:45]}...")
            
            try:
                result = categorize_expense(str(row["date"]), float(row["amount"]), str(row["description"]))
                results.append(result)
            except Exception as e:
                results.append({"category": "Uncategorized", "confidence": "low", 
                              "is_anomaly": False, "notes": str(e)})
            
            bar.progress((i + 1) / len(df))
            time.sleep(0.3)
        
        bar.empty()
        status.empty()
        
        df["category"] = [r["category"] for r in results]
        df["confidence"] = [r["confidence"] for r in results]
        df["is_anomaly"] = [r["is_anomaly"] for r in results]
        df["notes"] = [r["notes"] for r in results]
        
        st.session_state["df"] = df
        st.success("Done!")

    if "df" in st.session_state:
        df = st.session_state["df"]
        
        st.divider()
        
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total", f"${df['amount'].sum():,.2f}")
        c2.metric("Count", len(df))
        c3.metric("Average", f"${df['amount'].mean():,.2f}")
        c4.metric("Anomalies", int(df["is_anomaly"].sum()))
        
        tab1, tab2, tab3 = st.tabs(["All", "Categories", "Anomalies"])
        
        with tab1:
            st.dataframe(
                df[["date", "amount", "description", "category", "confidence", "notes"]]
                .style.format({"amount": "${:,.2f}"}),
                use_container_width=True, height=400
            )
            st.download_button("Download", df.to_csv(index=False), 
                             f"results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv", "text/csv")
        
        with tab2:
            summary = df.groupby("category")["amount"].agg(["count", "sum"]).reset_index()
            summary.columns = ["Category", "Count", "Total"]
            summary["Pct"] = (summary["Total"] / summary["Total"].sum() * 100).round(1)
            summary = summary.sort_values("Total", ascending=False)
            
            st.dataframe(summary.style.format({"Total": "${:,.2f}", "Pct": "{:.1f}%"}), 
                        use_container_width=True)
            st.bar_chart(summary.set_index("Category")["Total"])
        
        with tab3:
            anom = df[df["is_anomaly"] == True]
            if len(anom) == 0:
                st.success("No anomalies")
            else:
                st.warning(f"{len(anom)} flagged")
                for _, row in anom.iterrows():
                    with st.container(border=True):
                        col1, col2 = st.columns([2, 1])
                        col1.markdown(f"**{row['description']}**")
                        col1.caption(f"{row['date']} • {row['notes']}")
                        col2.metric("$", f"{row['amount']:,.2f}")


if __name__ == "__main__":
    main()