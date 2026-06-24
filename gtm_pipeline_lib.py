import duckdb
import pandas as pd
import os


def load_file(path: str) -> pd.DataFrame:
    ext = os.path.splitext(path)[1].lower()
    if ext == '.csv':
        return pd.read_csv(path)
    elif ext == '.xlsx':
        return pd.read_excel(path, engine='openpyxl')
    elif ext == '.xls':
        return pd.read_excel(path, engine='xlrd')
    raise ValueError(f"Unsupported file type: {ext}")


def build_insights(dispute_reasons_classifier_path: str,
                    prospect_dispute_data_path: str,
                    prospect_responded_disputes_path: str,
                    client_name: str) -> dict:
    """Runs the full cleaning + analysis pipeline and returns the insights dict
    that render_pdf_lib.render_pdf() consumes. Refactored from pipeline.py so it
    can be called from a service (FastAPI) instead of a standalone script."""

    dispute_reasons_classifier = load_file(dispute_reasons_classifier_path)
    prospect_dispute_data = load_file(prospect_dispute_data_path)
    prospect_responded_disputes = load_file(prospect_responded_disputes_path)

    conn = duckdb.connect()
    conn.register('dispute_reasons_classifier', dispute_reasons_classifier)
    conn.register('prospect_dispute_data', prospect_dispute_data)
    conn.register('prospect_responded_disputes', prospect_responded_disputes)

    # ----------------------------------------------------------------
    # CLEANING + DEDUPLICATION (single source of truth: dispute_status
    # AND terminal_event_code both come from the same chronological
    # latest-event resolution)
    # ----------------------------------------------------------------
    cleaning_query = """
    WITH RankedDisputeEvents AS (
        SELECT
            "eventDate", "pspReference", "originalReference", "chargebackSchemeCode",
            "paymentMethod", "chargebackReasonCode", "disputeStatus", "eventCode",
            "value", "autoDefended",
            MIN("eventDate") OVER(PARTITION BY "pspReference") as first_event_date,
            MAX(CASE WHEN CAST("autoDefended" AS VARCHAR) ILIKE 'true' THEN 1 ELSE 0 END)
                OVER(PARTITION BY "pspReference") as any_auto_defended,
            ROW_NUMBER() OVER(
                PARTITION BY "pspReference"
                ORDER BY "eventDate" DESC
            ) as event_rank
        FROM prospect_dispute_data
        WHERE "eventCode" != 'NOTIFICATION_OF_FRAUD'
    ),
    LatestDisputeStates AS (
        SELECT * FROM RankedDisputeEvents WHERE event_rank = 1
    ),
    DeduplicatedClassifier AS (
        SELECT
            TRIM(CAST("reason code" AS VARCHAR)) as clean_reason_code,
            MAX(chargeflow_reason) as chargeflow_reason
        FROM dispute_reasons_classifier
        GROUP BY TRIM(CAST("reason code" AS VARCHAR))
    )
    SELECT
        strftime(CAST(lds.first_event_date AS TIMESTAMP), '%Y-%m-%d %H:%M:%S') AS disputed_at,
        lds."pspReference" AS dispute_id,
        lds."originalReference" AS transaction_id,
        lds."chargebackSchemeCode" AS card_scheme,
        lds."paymentMethod" AS payment_method,
        COALESCE(classifier.chargeflow_reason, 'unclassified') AS dispute_reason,
        CASE
            WHEN lds."eventCode" = 'PRE_ARBITRATION_WON' THEN 'won'
            WHEN lds."eventCode" = 'ISSUER_RESPONSE_TIME_EXPIRED' THEN 'won'
            WHEN lds."eventCode" = 'PRE_ARBITRATION_LOST' THEN 'lost'
            WHEN lds."eventCode" = 'SECOND_CHARGEBACK' THEN 'lost'
            WHEN lds."eventCode" = 'DISPUTE_DEFENSE_PERIOD_ENDED' THEN 'lost'
            WHEN lds."eventCode" = 'CHARGEBACK_REVERSED' AND LOWER(lds."disputeStatus") = 'won' THEN 'won'
            WHEN lds."eventCode" = 'CHARGEBACK_REVERSED' THEN 'pending'
            WHEN LOWER(lds."disputeStatus") = 'won' THEN 'won'
            WHEN LOWER(lds."disputeStatus") IN ('lost', 'undefended', 'unresponded') THEN 'lost'
            ELSE 'pending'
        END AS dispute_status,
        lds."eventCode" AS terminal_event_code,
        lds."value" AS disputed_usd_amount,
        CASE
            WHEN lds.any_auto_defended = 1 THEN 'Adyen Auto-Defense'
            WHEN resp."originalReference" IS NOT NULL THEN 'Merchant'
            ELSE NULL
        END AS representment_defense_evidence_submitted_by
    FROM LatestDisputeStates lds
    LEFT JOIN DeduplicatedClassifier classifier
        ON TRIM(CAST(lds."chargebackReasonCode" AS VARCHAR)) = classifier.clean_reason_code
    LEFT JOIN (
        SELECT DISTINCT "originalReference" FROM prospect_responded_disputes
    ) resp ON lds."originalReference" = resp."originalReference"
    """

    clean_df = conn.execute(cleaning_query).df()
    assert clean_df['dispute_id'].is_unique, "CRITICAL: duplicate dispute_ids found!"
    conn.register('clean_disputes', clean_df)

    # ----------------------------------------------------------------
    # FINANCIAL METRICS
    # ----------------------------------------------------------------
    closed_df = clean_df[~clean_df['dispute_status'].isin(['pending'])]
    won_df = closed_df[closed_df['dispute_status'] == 'won']

    overall_win_rate = len(won_df) / len(closed_df) if len(closed_df) else 0
    overall_recovery_rate = (won_df['disputed_usd_amount'].sum() / closed_df['disputed_usd_amount'].sum()
                              if closed_df['disputed_usd_amount'].sum() else 0)

    merchant_df = closed_df[closed_df['representment_defense_evidence_submitted_by'].notna()]
    merchant_won_df = merchant_df[merchant_df['dispute_status'] == 'won']
    merchant_recovery_rate = (merchant_won_df['disputed_usd_amount'].sum() / merchant_df['disputed_usd_amount'].sum()
                               if merchant_df['disputed_usd_amount'].sum() else 0)
    merchant_win_rate = len(merchant_won_df) / len(merchant_df) if len(merchant_df) else 0

    ignored_df = closed_df[closed_df['representment_defense_evidence_submitted_by'].isna()]
    ignored_usd = ignored_df['disputed_usd_amount'].sum()
    ignored_count = len(ignored_df)
    opportunity_gap_usd = ignored_usd * merchant_recovery_rate

    # ----------------------------------------------------------------
    # SEGMENTATION
    # ----------------------------------------------------------------
    scheme_stats = {}
    for scheme in closed_df['card_scheme'].dropna().unique():
        s_df = closed_df[closed_df['card_scheme'] == scheme]
        s_won = s_df[s_df['dispute_status'] == 'won']
        scheme_stats[scheme] = {
            'total_usd': s_df['disputed_usd_amount'].sum(),
            'recovery_rate': (s_won['disputed_usd_amount'].sum() / s_df['disputed_usd_amount'].sum()
                               if s_df['disputed_usd_amount'].sum() else 0),
            'cases': len(s_df),
        }

    lost_df = closed_df[closed_df['dispute_status'] == 'lost']
    top_reasons = (lost_df.groupby('dispute_reason')['disputed_usd_amount']
                   .sum().sort_values(ascending=False).head(3))

    # ----------------------------------------------------------------
    # SLA / MISSED DEADLINES
    # ----------------------------------------------------------------
    timing_query = """
    WITH AlertEvents AS (
        SELECT "pspReference", MIN("eventDate") as first_alert_date
        FROM prospect_dispute_data
        WHERE "eventCode" IN ('NOTIFICATION_OF_CHARGEBACK', 'REQUEST_FOR_INFORMATION', 'NOTIFICATION_OF_FRAUD')
        GROUP BY "pspReference"
    ),
    ResponseEvents AS (
        SELECT "pspReference", MIN("eventDate") as first_response_date
        FROM prospect_dispute_data
        WHERE "eventCode" = 'INFORMATION_SUPPLIED'
        GROUP BY "pspReference"
    )
    SELECT
        a."pspReference" as dispute_id,
        a.first_alert_date,
        r.first_response_date
    FROM AlertEvents a
    LEFT JOIN ResponseEvents r ON a."pspReference" = r."pspReference"
    """
    timing_df = conn.execute(timing_query).df()
    timing_df['first_alert_date'] = pd.to_datetime(timing_df['first_alert_date'])
    timing_df['first_response_date'] = pd.to_datetime(timing_df['first_response_date'])
    timing_df['days_to_respond'] = (timing_df['first_response_date'] - timing_df['first_alert_date']).dt.days
    sla_merged = timing_df.merge(clean_df, on='dispute_id', how='left')

    sla_by_scheme = {}
    for scheme in sla_merged['card_scheme'].dropna().unique():
        sla_by_scheme[scheme] = sla_merged[sla_merged['card_scheme'] == scheme]['days_to_respond'].mean()

    missed_df = sla_merged[sla_merged['first_response_date'].isna()]
    missed_count = len(missed_df)
    missed_usd = missed_df['disputed_usd_amount'].sum()

    # ----------------------------------------------------------------
    # LIFECYCLE DROP-OFF (reuses terminal_event_code from clean_df)
    # ----------------------------------------------------------------
    lost_by_stage = (lost_df.groupby('terminal_event_code')['disputed_usd_amount']
                      .sum().sort_values(ascending=False))
    won_only = closed_df[closed_df['dispute_status'] == 'won']
    won_by_stage = (won_only.groupby('terminal_event_code')['disputed_usd_amount']
                    .sum().sort_values(ascending=False))

    top_loss_stage = lost_by_stage.index[0] if len(lost_by_stage) else None
    top_loss_stage_usd = lost_by_stage.iloc[0] if len(lost_by_stage) else 0
    top_win_stage = won_by_stage.index[0] if len(won_by_stage) else None
    top_win_stage_usd = won_by_stage.iloc[0] if len(won_by_stage) else 0

    date_min = pd.to_datetime(clean_df['disputed_at']).min().strftime('%Y-%m-%d')
    date_max = pd.to_datetime(clean_df['disputed_at']).max().strftime('%Y-%m-%d')

    insights = {
        'client_name': client_name,
        'period': f"{date_min} to {date_max}",
        'opportunity_gap_usd': opportunity_gap_usd,
        'ignored_count': ignored_count,
        'ignored_usd': ignored_usd,
        'overall_win_rate': overall_win_rate,
        'overall_recovery_rate': overall_recovery_rate,
        'active_win_rate': merchant_win_rate,
        'active_recovery_rate': merchant_recovery_rate,
        'scheme_stats': scheme_stats,
        'top_reasons': top_reasons.to_dict(),
        'sla_by_scheme': sla_by_scheme,
        'missed_count': missed_count,
        'missed_usd': missed_usd,
        'top_loss_stage': top_loss_stage,
        'top_loss_stage_usd': top_loss_stage_usd,
        'top_win_stage': top_win_stage,
        'top_win_stage_usd': top_win_stage_usd,
        'total_closed_cases': len(closed_df),
        'total_closed_usd': closed_df['disputed_usd_amount'].sum(),
    }
    return insights
