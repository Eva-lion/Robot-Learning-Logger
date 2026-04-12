"""Plotly Dash дашборд — визуализация качества данных."""

from __future__ import annotations

import dash
from dash import dcc, html, dash_table
from dash.dependencies import Input, Output

from src.memory_hub import db


def create_dashboard() -> dash.Dash:
    app = dash.Dash(
        __name__,
        title="Robot Learning Logger — Dashboard",
        suppress_callback_exceptions=True,
    )

    app.layout = html.Div(
        style={"fontFamily": "monospace", "padding": "20px", "backgroundColor": "#0f0f0f", "color": "#e0e0e0"},
        children=[
            html.H2("Robot Learning Logger — Quality Dashboard", style={"color": "#00ff88"}),
            dcc.Interval(id="interval", interval=10_000, n_intervals=0),

            html.Div(id="overview", style={"display": "flex", "gap": "20px", "marginBottom": "20px"}),

            html.Div([
                html.H4("Quality Score Trend"),
                dcc.Graph(id="quality-trend"),
            ], style={"marginBottom": "20px"}),

            html.Div([
                html.H4("Episodes by Status"),
                dcc.Graph(id="status-chart"),
            ], style={"marginBottom": "20px"}),

            html.Div([
                html.H4("Recent Episodes (last 20)"),
                html.Div(id="episodes-table"),
            ]),
        ],
    )

    @app.callback(
        [
            Output("overview", "children"),
            Output("quality-trend", "figure"),
            Output("status-chart", "figure"),
            Output("episodes-table", "children"),
        ],
        Input("interval", "n_intervals"),
    )
    def update(_n: int):  # type: ignore[no-untyped-def]
        import plotly.graph_objects as go

        summary = db.get_metrics_summary()
        episodes = db.get_episodes(limit=20)

        by_status = summary.get("by_status", {})
        total = summary.get("total_episodes", 0)
        ok = by_status.get("OK", 0) + by_status.get("APPROVED", 0)
        reject = by_status.get("REJECT", 0) + by_status.get("REJECTED_MANUAL", 0)
        auto_rate = f"{ok / total * 100:.1f}%" if total > 0 else "—"
        avg_score = summary.get("avg_quality_score") or "—"

        overview = [
            _card("Total Episodes", total),
            _card("OK / Approved", ok, color="#00ff88"),
            _card("Rejected", reject, color="#ff4444"),
            _card("Auto-verified rate", auto_rate),
            _card("Avg Quality Score", avg_score),
        ]

        scores = [(ep["started_at"], ep.get("quality_score") or 0) for ep in reversed(episodes) if ep.get("quality_score") is not None]
        if scores:
            xs, ys = zip(*scores)
            quality_fig = go.Figure(go.Scatter(x=list(xs), y=list(ys), mode="lines+markers", line={"color": "#00ff88"}))
        else:
            quality_fig = go.Figure()
        quality_fig.update_layout(
            paper_bgcolor="#1a1a1a", plot_bgcolor="#1a1a1a",
            font={"color": "#e0e0e0"}, margin={"t": 20, "b": 40},
            yaxis={"range": [0, 1]},
        )

        status_fig = go.Figure(go.Bar(
            x=list(by_status.keys()),
            y=list(by_status.values()),
            marker_color="#00aaff",
        ))
        status_fig.update_layout(
            paper_bgcolor="#1a1a1a", plot_bgcolor="#1a1a1a",
            font={"color": "#e0e0e0"}, margin={"t": 20, "b": 40},
        )

        cols = ["episode_id", "started_at", "status", "quality_score", "frame_count"]
        table = dash_table.DataTable(
            data=[{c: ep.get(c, "") for c in cols} for ep in episodes],
            columns=[{"name": c, "id": c} for c in cols],
            style_header={"backgroundColor": "#1a1a1a", "color": "#00ff88"},
            style_cell={"backgroundColor": "#0f0f0f", "color": "#e0e0e0", "fontSize": "12px"},
            style_data_conditional=[
                {"if": {"filter_query": '{status} = "REJECT"'}, "color": "#ff4444"},
                {"if": {"filter_query": '{status} = "OK"'}, "color": "#00ff88"},
                {"if": {"filter_query": '{status} = "APPROVED"'}, "color": "#00ff88"},
            ],
            page_size=20,
        )

        return overview, quality_fig, status_fig, table

    return app


def _card(label: str, value: object, color: str = "#e0e0e0") -> html.Div:
    return html.Div(
        style={
            "border": "1px solid #333",
            "borderRadius": "8px",
            "padding": "16px 24px",
            "minWidth": "140px",
            "backgroundColor": "#1a1a1a",
        },
        children=[
            html.Div(label, style={"fontSize": "11px", "color": "#888", "marginBottom": "6px"}),
            html.Div(str(value), style={"fontSize": "22px", "fontWeight": "bold", "color": color}),
        ],
    )


if __name__ == "__main__":
    from src.memory_hub.db import init_db
    init_db()
    dashboard_app = create_dashboard()
    dashboard_app.run(debug=False, host="127.0.0.1", port=8050)
