import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from sqlalchemy import create_engine, text
from datetime import datetime
import os

st.set_page_config(page_title="Economy Dashboard", page_icon="📊", layout="wide")

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "data", "db", "normalized.db")

def get_data():
    engine = create_engine(f'sqlite:///{DB_PATH}')
    df = pd.read_sql(text("""
        SELECT date, description, amount, category_name 
        FROM transactions 
        WHERE category_name IS NOT NULL
    """), engine)
    df['date'] = pd.to_datetime(df['date'])
    df['year_month'] = df['date'].dt.to_period('M').astype(str)
    return df

def main():
    st.title("📊 Economy Dashboard")

    df = get_data()

    if df.empty:
        st.warning("No data available. Run ingestion first.")
        return

    years = sorted(df['date'].dt.year.unique(), reverse=True)
    months = [
        ("01", "January"), ("02", "February"), ("03", "March"), ("04", "April"),
        ("05", "May"), ("06", "June"), ("07", "July"), ("08", "August"),
        ("09", "September"), ("10", "October"), ("11", "November"), ("12", "December")
    ]

    col1, col2 = st.columns(2)
    with col1:
        selected_year = st.selectbox("Year", years, index=0)
    with col2:
        selected_month = st.selectbox("Month", [f"{m[0]} - {m[1]}" for m in months], index=datetime.now().month - 1)

    month_code = selected_month.split(" - ")[0]
    current_period = f"{selected_year}-{month_code}"

    df_period = df[df['year_month'] == current_period]
    df_expenses = df_period[df_period['amount'] < 0].copy()
    df_income = df_period[df_period['amount'] > 0].copy()

    total_income = df_income['amount'].sum()
    total_expenses = abs(df_expenses['amount'].sum())
    net = total_income - total_expenses

    st.markdown("---")
    m1, m2, m3 = st.columns(3)
    m1.metric("Total Income (€)", f"{total_income:,.2f}")
    m2.metric("Total Expenses (€)", f"{total_expenses:,.2f}")
    m3.metric("Net Balance (€)", f"{net:,.2f}", delta_color="normal" if net >= 0 else "inverse")
    st.markdown("---")

    col_chart1, col_chart2 = st.columns(2)

    with col_chart1:
        st.subheader(f"Expenses by Category ({current_period})")
        if df_expenses.empty:
            st.info("No expenses for this period")
        else:
            cat_sum = df_expenses.groupby('category_name')['amount'].sum().abs().reset_index()
            cat_sum.columns = ['category', 'amount']
            cat_sum = cat_sum.sort_values('amount', ascending=False)

            fig_pie = px.pie(
                cat_sum, 
                values='amount', 
                names='category',
                hole=0.4,
                labels={'amount': '€', 'category': 'Category'},
                title=f"Expenses Distribution - {current_period}"
            )
            fig_pie.update_traces(textinfo='label+value')
            fig_pie.update_layout(showlegend=True, legend=dict(orientation="h", yanchor="bottom", y=-0.3))
            st.plotly_chart(fig_pie, width='stretch')

            categories = ["All"] + cat_sum['category'].tolist()
            selected_category = st.selectbox("Select Category", categories, key="cat_select")

            if selected_category != "All":
                cat_transactions = df_expenses[df_expenses['category_name'] == selected_category][['date', 'description', 'amount']].copy()
                cat_transactions['amount'] = cat_transactions['amount'].abs()
                st.dataframe(cat_transactions, use_container_width=True)

    with col_chart2:
        st.subheader("Monthly Expenses")
        monthly_exp = df[df['amount'] < 0].groupby('year_month')['amount'].sum().abs().reset_index()
        monthly_exp.columns = ['month', 'amount']
        monthly_exp = monthly_exp.sort_values('month')
        monthly_exp['label'] = pd.to_datetime(monthly_exp['month']).dt.strftime('%b %Y')

        fig_bar = px.bar(
            monthly_exp, 
            x='label', 
            y='amount',
            text_auto='.2s',
            labels={'label': 'Month', 'amount': 'Expenses (€)'},
            title="Total Expenses by Month"
        )
        fig_bar.update_traces(textposition='outside')
        fig_bar.update_layout(xaxis_title="Month", yaxis_title="€", xaxis=dict(tickangle=-45))
        st.plotly_chart(fig_bar, width='stretch')

    st.markdown("---")
    st.subheader("Cumulative Expenses by Category")

    monthly_cat = df[df['amount'] < 0].groupby(['year_month', 'category_name'])['amount'].sum().abs().reset_index()
    monthly_cat.columns = ['month', 'category', 'amount']
    monthly_cat = monthly_cat.sort_values('month')
    monthly_cat['label'] = pd.to_datetime(monthly_cat['month']).dt.strftime('%b %Y')

    if not monthly_cat.empty:
        pivot_df = monthly_cat.pivot(index='label', columns='category', values='amount').fillna(0)
        pivot_df = pivot_df.sort_index()

        fig_stacked = go.Figure()
        categories = pivot_df.columns.tolist()
        colors = px.colors.qualitative.Set3[:len(categories)]

        for i, cat in enumerate(categories):
            fig_stacked.add_trace(go.Bar(
                name=cat,
                x=pivot_df.index,
                y=pivot_df[cat],
                marker_color=colors[i % len(colors)]
            ))

        fig_stacked.update_layout(
            barmode='stack',
            xaxis_title="Month",
            yaxis_title="Expenses (€)",
            xaxis=dict(tickangle=-45),
            legend_title="Category",
            legend=dict(orientation="h", yanchor="bottom", y=-0.2),
            height=400
        )
        st.plotly_chart(fig_stacked, width='stretch')

if __name__ == "__main__":
    main()