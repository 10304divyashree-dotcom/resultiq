"""
routes/report.py
================
Module 6 — Report Generation routes.

POST /report/generate
    Accepts file_id + sheet_name, calls services.reporter.generate_report(),
    persists a Report record, redirects to the preview page.

GET  /report/<report_id>
    Renders the report preview page with summary stats and data table.

GET  /report/<report_id>/download
    Streams the generated Excel file for download.
"""

import os
import uuid
from datetime import datetime, timezone

from flask import (
    Blueprint, render_template, redirect, url_for,
    flash, request, abort, current_app, send_file
)
from flask_login import login_required, current_user

from models import db, UploadedFile, Report, ActivityLog
from services.reporter import generate_report
import pandas as pd

report_bp = Blueprint('report', __name__)


# ------------------------------------------------------------------ #
# POST /report/generate
# ------------------------------------------------------------------ #

@report_bp.route('/report/generate', methods=['POST'])
@login_required
def generate():
    """Generate a results report from a classified workbook sheet."""

    file_id    = request.form.get('file_id', '').strip()
    sheet_name = request.form.get('sheet_name', '').strip()

    # --- Validate inputs ---
    if not file_id:
        flash('No file specified for report generation.', 'danger')
        return redirect(url_for('upload.upload'))

    record = db.session.get(UploadedFile, file_id)
    if record is None or record.user_id != current_user.id:
        abort(404)

    if not sheet_name:
        # Fall back to the first sheet that has marks columns
        for sheet in (record.worksheets or []):
            if any(c.get('classification') == 'marks'
                   for c in sheet.get('columns', [])):
                sheet_name = sheet['name']
                break

    if not sheet_name:
        flash('No sheet with analysed MARKS columns was found. '
              'Please run column analysis first.', 'danger')
        return redirect(url_for('analyse.analyse', file_id=file_id))

    worksheets = record.worksheets or []

    # Verify the sheet has been analysed (has classification keys)
    target_sheet = next(
        (s for s in worksheets if s.get('name') == sheet_name), None
    )
    if target_sheet is None:
        flash(f"Sheet '{sheet_name}' not found in analysis data.", 'danger')
        return redirect(url_for('analyse.analyse', file_id=file_id))

    has_classifications = any(
        'classification' in col
        for col in target_sheet.get('columns', [])
    )
    if not has_classifications:
        flash('Columns have not been analysed yet. '
              'Please run the analysis step first.', 'warning')
        return redirect(url_for('analyse.analyse', file_id=file_id))

    # --- Create Report record (pending) ---
    report_filename = (
        f"ResultIQ_Report_{record.original_filename.rsplit('.', 1)[0]}"
        f"_{sheet_name}_{uuid.uuid4().hex[:6]}.xlsx"
    )
    report_name = (
        f"{record.original_filename.rsplit('.', 1)[0]} — {sheet_name}"
    )
    report_folder = current_app.config['REPORT_FOLDER']
    report_path   = os.path.join(report_folder, report_filename)

    report_record = Report(
        user_id=current_user.id,
        uploaded_file_id=file_id,
        original_filename=record.original_filename,
        report_name=report_name,
        sheet_name=sheet_name,
        requested_columns=[
            col['name'] for col in target_sheet.get('columns', [])
            if col.get('classification') == 'marks'
        ],
        report_path=report_path,
        status='processing',
    )
    try:
        db.session.add(report_record)
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        current_app.logger.error(f'Report DB create error: {exc}')
        flash('Could not initialise report record. Please try again.', 'danger')
        return redirect(url_for('analyse.analyse', file_id=file_id))

    # --- Generate the report ---
    try:
        stats = generate_report(
            source_filepath=record.file_path,
            worksheets_json=worksheets,
            sheet_name=sheet_name,
            output_filepath=report_path,
        )
    except ValueError as exc:
        # Update record to failed
        report_record.status        = 'failed'
        report_record.error_message = str(exc)
        db.session.commit()
        flash(f'Report generation failed: {exc}', 'danger')
        return redirect(url_for('analyse.analyse', file_id=file_id))
    except Exception as exc:
        report_record.status        = 'failed'
        report_record.error_message = str(exc)
        db.session.commit()
        current_app.logger.error(f'Unexpected report error: {exc}')
        flash('An unexpected error occurred while generating the report.', 'danger')
        return redirect(url_for('analyse.analyse', file_id=file_id))

    # --- Mark as completed, store analysis trace ---
    report_record.status          = 'completed'
    report_record.generated_at    = datetime.now(timezone.utc)
    report_record.analysis_trace  = stats

    log = ActivityLog(
        user_id=current_user.id,
        activity_type='REPORT_GENERATED',
        description=(
            f"Generated report for '{record.original_filename}' "
            f"sheet '{sheet_name}': "
            f"{stats['total_students']} students, "
            f"{stats['pass_count']} pass, {stats['fail_count']} fail."
        )
    )
    try:
        db.session.add(log)
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        current_app.logger.error(f'Report finalise DB error: {exc}')
        # Report file was created — still redirect to preview

    if stats.get('absent', 0) > 0:
        flash(
            f'Report generated successfully! '
            f'{stats["pass_count"]} of {stats["appeared"]} appeared students passed '
            f'({stats["pass_rate"]}%) [{stats["absent"]} absent of {stats["total_students"]} total].',
            'success'
        )
    else:
        flash(
            f'Report generated successfully! '
            f'{stats["pass_count"]} of {stats["total_students"]} students passed '
            f'({stats["pass_rate"]}%).',
            'success'
        )
    return redirect(url_for('report.preview', report_id=report_record.id))


# ------------------------------------------------------------------ #
# GET /report/<report_id>  — Preview
# ------------------------------------------------------------------ #

@report_bp.route('/report/<report_id>')
@login_required
def preview(report_id: str):
    """Render the report preview page."""

    report = db.session.get(Report, report_id)
    if report is None or report.user_id != current_user.id:
        abort(404)

    if report.status == 'failed':
        flash(f'This report failed to generate: {report.error_message}', 'danger')
        return redirect(url_for('upload.upload'))

    if report.status != 'completed' or not report.report_path:
        flash('This report is not ready yet.', 'warning')
        return redirect(url_for('upload.upload'))

    # --- Read the generated Excel to display the data table ---
    table_rows  = []
    table_cols  = []
    read_error  = None
    try:
        uploaded_file = db.session.get(UploadedFile, report.uploaded_file_id) if report.uploaded_file_id else None
        target_sheet = next(
            (s for s in (uploaded_file.worksheets or []) if s.get('name') == report.sheet_name),
            None
        ) if uploaded_file else None
        header_idx = target_sheet.get('header_row_index', 0) if target_sheet else 0
        df = pd.read_excel(report.report_path, sheet_name=report.sheet_name,
                           header=header_idx, engine='openpyxl')
        table_cols = list(df.columns)
        
        # Since the header row might contain actual data values, we assume S.No is the first column (index 0)
        sno_idx = 0

        # Replace NaN with blank for display
        df = df.fillna('')
        raw_rows = df.values.tolist()
        table_rows = []
        for row_idx, row in enumerate(raw_rows):
            cleaned_row = []
            for i, item in enumerate(row):
                if i == sno_idx:
                    cleaned_row.append(row_idx + 1)
                elif isinstance(item, float) and item.is_integer():
                    cleaned_row.append(int(item))
                else:
                    cleaned_row.append(item)
            table_rows.append(cleaned_row)
    except Exception as exc:
        read_error = str(exc)
        current_app.logger.error(f'Preview read error for {report_id}: {exc}')

    stats = report.analysis_trace or {}

    # Backward compatibility: ensure per_column_stats is complete with all 8 metrics
    if not read_error and 'df' in locals() and df is not None and not df.empty:
        try:
            col_stats = stats.get('per_column_stats', {})
            needs_backfill = (
                not col_stats or
                any('avg_percentage' not in v for v in col_stats.values())
            )
            if needs_backfill:
                marks_cols = [
                    c for c in (stats.get('marks_columns') or table_cols)
                    if c in df.columns and c not in ('Sl.No', 'S.No', 'Roll No', 'Name', 'Total Marks', 'Average', 'Percentage', 'Result', 'Subjects Appeared')
                ]
                if marks_cols:
                    from services.reporter import _compute_results_per_column
                    new_pcs = _compute_results_per_column(df, marks_cols)
                    if not col_stats:
                        stats['per_column_stats'] = new_pcs
                    else:
                        for k, v in new_pcs.items():
                            if k in col_stats:
                                col_stats[k].update(v)
        except Exception as exc:
            current_app.logger.warning(f'Could not backfill per-column stats: {exc}')

    # Safe normalization: guarantee all keys exist for any legacy report
    total_st = stats.get('total_students', 0)
    for col_k, col_v in stats.get('per_column_stats', {}).items():
        if isinstance(col_v, dict):
            if 'total_students' not in col_v:
                col_v['total_students'] = total_st
            if 'appeared' not in col_v:
                col_v['appeared'] = col_v['total_students']
            if 'absent' not in col_v:
                col_v['absent'] = max(0, col_v['total_students'] - col_v['appeared'])
            if 'pass_count' not in col_v:
                col_v['pass_count'] = 0
            if 'fail_count' not in col_v:
                col_v['fail_count'] = 0
            if 'pass_rate' not in col_v:
                col_v['pass_rate'] = round((col_v['pass_count'] / col_v['appeared'] * 100), 2) if col_v['appeared'] > 0 else 0.0
            if 'overall_pass_rate' not in col_v:
                col_v['overall_pass_rate'] = round((col_v['pass_count'] / col_v['total_students'] * 100), 2) if col_v['total_students'] > 0 else 0.0
            if 'avg_percentage' not in col_v:
                col_v['avg_percentage'] = stats.get('avg_percentage', 0.0)
            if 'highest_pct' not in col_v:
                col_v['highest_pct'] = stats.get('highest_pct', 0.0)
            if 'lowest_pct' not in col_v:
                col_v['lowest_pct'] = stats.get('lowest_pct', 0.0)

    return render_template(
        'report/preview.html',
        report=report,
        stats=stats,
        table_cols=table_cols,
        table_rows=table_rows,
        read_error=read_error,
    )


# ------------------------------------------------------------------ #
# GET /report/<report_id>/download
# ------------------------------------------------------------------ #

@report_bp.route('/report/<report_id>/download')
@login_required
def download(report_id: str):
    """Stream the generated report file for download."""

    report = db.session.get(Report, report_id)
    if report is None or report.user_id != current_user.id:
        abort(404)

    if report.status != 'completed' or not report.report_path:
        flash('Report file is not available for download.', 'warning')
        return redirect(url_for('report.preview', report_id=report_id))

    if not os.path.isfile(report.report_path):
        abort(404)

    # Record download timestamp
    try:
        report.downloaded_at = datetime.now(timezone.utc)
        db.session.commit()
    except Exception:
        db.session.rollback()

    download_name = (
        f"ResultIQ_{report.report_name.replace(' ', '_').replace('—', '-')}.xlsx"
    )

    return send_file(
        report.report_path,
        as_attachment=True,
        download_name=download_name,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )


# ------------------------------------------------------------------ #
# GET /reports  — History List
# ------------------------------------------------------------------ #

@report_bp.route('/reports')
@login_required
def history():
    """List all generated reports for the current user."""
    # Fetch all reports descending
    reports = (Report.query
               .filter_by(user_id=current_user.id)
               .order_by(Report.generated_at.desc())
               .all())
    
    return render_template('report/history.html', reports=reports)
