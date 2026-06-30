from dataclasses import dataclass
from datetime import timedelta
from typing import List

from django.db.models import Max, Q
from django.urls import NoReverseMatch, reverse
from django.utils import timezone
from django.utils.text import slugify

from .models import (
    AnnualTrustComplianceRecord,
    Section19ComplianceReview,
    TrustMonthlyRecord,
    TrustAccountingPeriod,
    PowerMoneyDealing,
    PowerMoneyEntry,
    TransitMoneyEntry,
    WrittenDirection,
    AuthorisedSignatory,
    ControlledMoneyAccount,
    ControlledMoneyMonthlyStatement,
    MatterLedger,
    MonthlyReconciliation,
    ReconciliationBankLine,
    Receipt,
    StatutoryDepositRecord,
    TrustAccount,
    TrustInvestment,
    add_nsw_working_days,
    UnclaimedMoneyRecord
)


@dataclass
class ComplianceAlert:
    severity: str
    category: str
    title: str
    description: str
    action_url: str = ""
    matter: object = None
    alert_key: str = ""


class ComplianceService:
    OLD_BALANCE_DAYS = 90
    NOTICE_REMINDER_DAYS = 7
    REVIEW_REMINDER_DAYS = 30
    SIGNATORY_REVIEW_REMINDER_DAYS = 30
    TRANSIT_MONEY_PENDING_DAYS = 7
    INVESTMENT_MATURITY_REMINDER_DAYS = 30

    def __init__(self, firm):
        self.firm = firm

    def build_alert_key(self, alert):
        matter_id = getattr(alert.matter, "pk", "") if alert.matter else ""
        raw = "|".join([
            str(alert.severity or ""),
            str(alert.category or ""),
            str(alert.title or ""),
            str(matter_id or ""),
            str(alert.action_url or ""),
        ])
        return slugify(raw)[:240]

    def url_or_fallback(self, name, kwargs=None, fallback=""):
        try:
            return reverse(name, kwargs=kwargs or {})
        except NoReverseMatch:
            return fallback

    def get_alerts(self) -> List[ComplianceAlert]:
        alerts = []
        alerts.extend(self.annual_trust_compliance_alerts())
        alerts.extend(self.periodic_trust_review_alerts())
        alerts.extend(self.trust_account_notice_alerts())
        alerts.extend(self.reconciliation_alerts())
        alerts.extend(self.monthly_record_integrity_alerts())
        alerts.extend(self.reconciliation_bank_line_alerts())
        alerts.extend(self.receipt_banking_alerts())
        alerts.extend(self.controlled_money_alerts())
        alerts.extend(self.statutory_deposit_alerts())
        alerts.extend(self.authorised_signatory_alerts())
        alerts.extend(self.written_direction_alerts())
        alerts.extend(self.transit_money_alerts())
        alerts.extend(self.power_money_alerts())
        alerts.extend(self.investment_alerts())
        alerts.extend(self.unclaimed_money_alerts())
        alerts.extend(self.old_trust_balance_alerts())

        priority = {
            "Action Required": 1,
            "Review Required": 2,
            "Reminder": 3,
            "Information": 4,
        }

        for alert in alerts:
            if not alert.alert_key:
                alert.alert_key = self.build_alert_key(alert)

        return sorted(
            alerts,
            key=lambda alert: (
                priority.get(alert.severity, 99),
                alert.category,
                alert.title
)
        )

    def get_status(self):
        alerts = self.get_alerts()

        action_count = len([a for a in alerts if a.severity == "Action Required"])
        review_count = len([a for a in alerts if a.severity == "Review Required"])
        reminder_count = len([a for a in alerts if a.severity == "Reminder"])
        info_count = len([a for a in alerts if a.severity == "Information"])

        if action_count:
            overall = "Action Required"
        elif review_count:
            overall = "Review Required"
        elif reminder_count:
            overall = "Reminder"
        else:
            overall = "Good"

        return {
            "overall": overall,
            "action_count": action_count,
            "review_count": review_count,
            "reminder_count": reminder_count,
            "info_count": info_count,
            "total_count": len(alerts),
            "last_checked": timezone.now(),
            "alerts": alerts,
        }

    def previous_month_end(self):
        today = timezone.localdate()
        first_day_this_month = today.replace(day=1)
        return first_day_this_month - timedelta(days=1)

    def annual_trust_compliance_alerts(self):
        alerts = []
        today = timezone.localdate()

        if today.month >= 4:
            trust_year_end = today.replace(month=3, day=31)
        else:
            trust_year_end = today.replace(year=today.year - 1, month=3, day=31)

        trust_year_start = trust_year_end.replace(year=trust_year_end.year - 1) + timedelta(days=1)

        part_a_due = trust_year_end.replace(month=4, day=30)
        part_b_due = trust_year_end.replace(month=5, day=31)

        record = (
            AnnualTrustComplianceRecord.objects
            .filter(
                firm=self.firm,
                trust_year_start__lte=trust_year_end,
                trust_year_end__gte=trust_year_start
)
            .order_by("-trust_year_end", "-created_at")
            .first()
        )

        create_url = self.url_or_fallback("trust:annual_compliance_create")
        list_url = self.url_or_fallback("trust:annual_compliance_list")

        if not record:
            severity = "Action Required" if today > part_a_due else "Reminder"
            alerts.append(ComplianceAlert(
                severity=severity,
                category="Annual trust compliance",
                title="Annual trust compliance record not created",
                description=(
                    f"No annual trust compliance record has been created for the trust year "
                    f"{trust_year_start.strftime('%d %b %Y')} to {trust_year_end.strftime('%d %b %Y')}."
                ),
                action_url=create_url
))
            return alerts

        update_url = self.url_or_fallback(
            "trust:annual_compliance_update",
            kwargs={"pk": record.pk},
            fallback=list_url
)

        if record.status == AnnualTrustComplianceRecord.STATUS_REQUIRES_ACTION:
            alerts.append(ComplianceAlert(
                severity="Review Required",
                category="Annual trust compliance",
                title="Annual trust compliance record requires action",
                description=(
                    f"The annual trust compliance record for "
                    f"{record.trust_year_start.strftime('%d %b %Y')} to "
                    f"{record.trust_year_end.strftime('%d %b %Y')} is marked as requiring action."
                ),
                action_url=update_url
))

        if not record.part_a_completed_on:
            severity = "Action Required" if today > part_a_due else "Reminder"
            alerts.append(ComplianceAlert(
                severity=severity,
                category="Annual trust compliance",
                title="Annual trust confirmation not recorded",
                description=(
                    f"Annual trust confirmation (Part A) completion has not been recorded for the trust year "
                    f"ending {record.trust_year_end.strftime('%d %b %Y')}."
                ),
                action_url=update_url
))

        if record.part_b_required and not record.part_b_completed_on:
            severity = "Action Required" if today > part_b_due else "Reminder"
            alerts.append(ComplianceAlert(
                severity=severity,
                category="Annual trust compliance",
                title="Statement of Trust Money not recorded",
                description=(
                    f"Statement of Trust Money (Part B) is marked as required, but no lodged/completed date "
                    f"has been recorded for the trust year ending {record.trust_year_end.strftime('%d %b %Y')}."
                ),
                action_url=update_url
))

        if record.external_examiner_required and not record.external_examiner_report_lodged_on:
            severity = "Action Required" if today > part_b_due else "Reminder"
            alerts.append(ComplianceAlert(
                severity=severity,
                category="Annual trust compliance",
                title="External Examiner Report lodgement not recorded",
                description=(
                    f"External Examiner Report is marked as required, but no lodgement date has been recorded "
                    f"for the trust year ending {record.trust_year_end.strftime('%d %b %Y')}."
                ),
                action_url=update_url
))

        missing_documents = []
        if not record.bank_reconciliation_31_march:
            missing_documents.append("bank reconciliation as at 31 March")
        if not record.trial_balance_31_march:
            missing_documents.append("trial balance as at 31 March")
        if not record.bank_statement_31_march:
            missing_documents.append("bank statement as at 31 March")

        if missing_documents:
            alerts.append(ComplianceAlert(
                severity="Review Required",
                category="Annual trust compliance",
                title="Annual supporting documents incomplete",
                description=(
                    "The annual trust compliance record is missing: "
                    + ", ".join(missing_documents)
                    + "."
                ),
                action_url=update_url
))

        if record.external_examiner_required:
            if not record.overdrawn_ledgers_reviewed:
                alerts.append(ComplianceAlert(
                    severity="Review Required",
                    category="Annual trust compliance",
                    title="Overdrawn ledgers review not recorded",
                    description="The annual record does not confirm that overdrawn ledgers were reviewed.",
                    action_url=update_url
))

            if not record.controlled_money_listing_reviewed:
                alerts.append(ComplianceAlert(
                    severity="Review Required",
                    category="Annual trust compliance",
                    title="Controlled money listing review not recorded",
                    description="The annual record does not confirm that the controlled money listing was reviewed.",
                    action_url=update_url
))

            if not record.investment_money_listing_reviewed:
                alerts.append(ComplianceAlert(
                    severity="Review Required",
                    category="Annual trust compliance",
                    title="Investment money listing review not recorded",
                    description="The annual record does not confirm that the investment money listing was reviewed.",
                    action_url=update_url
))

        return alerts


    def periodic_trust_review_alerts(self):
        alerts = []
        today = timezone.localdate()

        trust_year_start_year = today.year if today.month >= 4 else today.year - 1
        current_start = today.replace(year=trust_year_start_year, month=4, day=1)
        current_end = today.replace(year=trust_year_start_year + 1, month=3, day=31)

        current_reviews = Section19ComplianceReview.objects.filter(
            firm=self.firm,
            review_period_start__lte=current_end,
            review_period_end__gte=current_start
)

        latest_review = (
            Section19ComplianceReview.objects
            .filter(firm=self.firm)
            .order_by("-review_period_end", "-created_at")
            .first()
        )

        create_url = self.url_or_fallback(
            "trust:periodic_compliance_review_create",
            fallback=self.url_or_fallback("trust:section19_review_create")
)
        list_url = self.url_or_fallback(
            "trust:periodic_compliance_review_list",
            fallback=self.url_or_fallback("trust:section19_review_list")
)

        if not current_reviews.exists():
            alerts.append(ComplianceAlert(
                severity="Reminder",
                category="Periodic trust review",
                title="Periodic trust compliance review not recorded",
                description=(
                    f"No periodic trust compliance review has been recorded for the current trust year "
                    f"({current_start.strftime('%d %b %Y')} to {current_end.strftime('%d %b %Y')}). "
                    "This is an internal examiner-readiness reminder."
                ),
                action_url=create_url
))

        if latest_review and latest_review.status == Section19ComplianceReview.STATUS_REQUIRES_ACTION:
            alerts.append(ComplianceAlert(
                severity="Review Required",
                category="Periodic trust review",
                title="Periodic trust compliance review requires action",
                description=(
                    f"The periodic trust compliance review for "
                    f"{latest_review.review_period_start.strftime('%d %b %Y')} to "
                    f"{latest_review.review_period_end.strftime('%d %b %Y')} is marked as requiring action."
                ),
                action_url=self.url_or_fallback(
                    "trust:periodic_compliance_review_update",
                    kwargs={"pk": latest_review.pk},
                    fallback=list_url
)
))

        return alerts


    def trust_account_notice_alerts(self):
        if not self.firm:
            return []

        today = timezone.localdate()
        reminder_cutoff = today + timedelta(days=self.NOTICE_REMINDER_DAYS)

        trust_accounts = TrustAccount.objects.filter(
            firm=self.firm,
            is_general=True
)

        alerts = []

        for trust_account in trust_accounts:
            opening_due = trust_account.opening_notice_due_on

            if (
                trust_account.opened_on
                and opening_due
                and not trust_account.law_society_opening_notice_sent_on
            ):
                if today > opening_due:
                    alerts.append(
                        ComplianceAlert(
                            severity="Action Required",
                            category="Trust account notice",
                            title="Trust account opening notice is overdue",
                            description=(
                                f"{trust_account.name} was opened on {trust_account.opened_on}. "
                                f"The opening notice was due on {opening_due} and has not been recorded."
                            ),
                            action_url="/trust/accounts/"
)
                    )
                elif opening_due <= reminder_cutoff:
                    alerts.append(
                        ComplianceAlert(
                            severity="Reminder",
                            category="Trust account notice",
                            title="Trust account opening notice due soon",
                            description=(
                                f"{trust_account.name} was opened on {trust_account.opened_on}. "
                                f"Record the opening notice by {opening_due}."
                            ),
                            action_url="/trust/accounts/"
)
                    )

            closure_due = trust_account.closure_notice_due_on

            if (
                trust_account.closed_on
                and closure_due
                and not trust_account.law_society_closure_notice_sent_on
            ):
                if today > closure_due:
                    alerts.append(
                        ComplianceAlert(
                            severity="Action Required",
                            category="Trust account notice",
                            title="Trust account closure notice is overdue",
                            description=(
                                f"{trust_account.name} was closed on {trust_account.closed_on}. "
                                f"The closure notice was due on {closure_due} and has not been recorded."
                            ),
                            action_url="/trust/accounts/"
)
                    )
                elif closure_due <= reminder_cutoff:
                    alerts.append(
                        ComplianceAlert(
                            severity="Reminder",
                            category="Trust account notice",
                            title="Trust account closure notice due soon",
                            description=(
                                f"{trust_account.name} was closed on {trust_account.closed_on}. "
                                f"Record the closure notice by {closure_due}."
                            ),
                            action_url="/trust/accounts/"
)
                    )

        return alerts

    def reconciliation_alerts(self):
        if not self.firm:
            return []

        today = timezone.localdate()
        period_end = self.previous_month_end()
        due_date = add_nsw_working_days(period_end, 15)

        trust_accounts = TrustAccount.objects.filter(
            firm=self.firm,
            is_active=True,
            is_general=True,
            opened_on__lte=period_end
)

        alerts = []

        for trust_account in trust_accounts:
            reconciliation = MonthlyReconciliation.objects.filter(
                trust_account=trust_account,
                period_end=period_end
).first()

            if reconciliation and reconciliation.is_finalised:
                continue

            if today > due_date:
                title = "Monthly reconciliation is overdue"
                severity = "Action Required"
                category = "Reconciliation overdue"
            else:
                title = "Monthly reconciliation due"
                severity = "Reminder"
                category = "Reconciliation due"

            if reconciliation:
                description = (
                    f"{trust_account.name} has a reconciliation started for "
                    f"{period_end:%B %Y}, but it has not yet been finalised. "
                    f"The due date is {due_date}."
                )
            else:
                description = (
                    f"{trust_account.name} requires a monthly reconciliation for "
                    f"{period_end:%B %Y}. The due date is {due_date}."
                )

            alerts.append(
                ComplianceAlert(
                    severity=severity,
                    category=category,
                    title=title,
                    description=description,
                    action_url="/trust/reconciliations/"
)
            )

        return alerts

    def monthly_record_integrity_alerts(self):
        if not self.firm:
            return []

        alerts = []

        required_records = [
            TrustMonthlyRecord.RECORD_RECEIPTS_CASH_BOOK,
            TrustMonthlyRecord.RECORD_PAYMENTS_CASH_BOOK,
            TrustMonthlyRecord.RECORD_TRUST_TRANSFER_JOURNAL,
            TrustMonthlyRecord.RECORD_TRIAL_BALANCE,
            TrustMonthlyRecord.RECORD_RECONCILIATION_STATEMENT,
        ]

        record_labels = dict(TrustMonthlyRecord.RECORD_TYPE_CHOICES)

        reconciliations = (
            MonthlyReconciliation.objects
            .filter(
                trust_account__firm=self.firm,
                is_finalised=True
)
            .select_related("trust_account", "accounting_period")
            .order_by("-period_end")
        )

        for reconciliation in reconciliations:
            action_url = "/trust/reconciliations/"

            if not reconciliation.accounting_period_id:
                alerts.append(
                    ComplianceAlert(
                        severity="Action Required",
                        category="Monthly trust records",
                        title="Finalised reconciliation is not linked to an accounting period",
                        description=(
                            f"{reconciliation.trust_account.name} has a finalised reconciliation for "
                            f"{reconciliation.period_end:%B %Y}, but no accounting period is linked."
                        ),
                        action_url=action_url
)
                )
                continue

            existing_records = set(
                reconciliation.accounting_period.monthly_records.values_list(
                    "record_type",
                    flat=True
)
            )

            missing_records = [
                record_labels.get(record_type, record_type)
                for record_type in required_records
                if record_type not in existing_records
            ]

            if missing_records:
                alerts.append(
                    ComplianceAlert(
                        severity="Action Required",
                        category="Monthly trust records",
                        title="Required monthly trust records are missing",
                        description=(
                            f"{reconciliation.trust_account.name} has a finalised reconciliation for "
                            f"{reconciliation.period_end:%B %Y}, but the following monthly records are missing: "
                            f"{', '.join(missing_records)}."
                        ),
                        action_url=action_url
)
                )

            if reconciliation.accounting_period.status != TrustAccountingPeriod.STATUS_LOCKED:
                alerts.append(
                    ComplianceAlert(
                        severity="Review Required",
                        category="Accounting period",
                        title="Finalised accounting period is not locked",
                        description=(
                            f"{reconciliation.trust_account.name} has a finalised reconciliation for "
                            f"{reconciliation.period_end:%B %Y}, but the accounting period remains open."
                        ),
                        action_url=action_url
)
                )

            if reconciliation.working_days_late:
                alerts.append(
                    ComplianceAlert(
                        severity="Review Required",
                        category="Monthly reconciliation timing",
                        title="Monthly reconciliation was prepared late",
                        description=(
                            f"{reconciliation.trust_account.name} reconciliation for "
                            f"{reconciliation.period_end:%B %Y} was prepared "
                            f"{reconciliation.working_days_late} working days late."
                        ),
                        action_url=action_url
)
                )

        return alerts

    def reconciliation_bank_line_alerts(self):
        if not self.firm:
            return []

        bank_lines = (
            ReconciliationBankLine.objects
            .filter(
                reconciliation__trust_account__firm=self.firm,
                reconciliation__is_finalised=False
)
            .filter(
                Q(adjustment_category="") |
                Q(adjustment_category=ReconciliationBankLine.ADJUSTMENT_CATEGORY_UNIDENTIFIED_DEPOSIT) |
                Q(adjustment_category=ReconciliationBankLine.ADJUSTMENT_CATEGORY_BANK_DEBIT_NOT_CASH_BOOK)
            )
            .select_related("reconciliation", "reconciliation__trust_account")
            .order_by("-reconciliation__period_end", "line_date")
        )

        alerts = []

        for line in bank_lines:
            trust_account = line.reconciliation.trust_account
            period_end = line.reconciliation.period_end

            if line.adjustment_category == ReconciliationBankLine.ADJUSTMENT_CATEGORY_UNIDENTIFIED_DEPOSIT:
                alerts.append(
                    ComplianceAlert(
                        severity="Action Required",
                        category="Unidentified deposit",
                        title="Unidentified deposit requires allocation",
                        description=(
                            f"{trust_account.name} has an unidentified deposit of "
                            f"${line.amount} dated {line.line_date} in the {period_end:%B %Y} reconciliation."
                        ),
                        action_url="/trust/reconciliations/"
)
                )
            elif line.adjustment_category == ReconciliationBankLine.ADJUSTMENT_CATEGORY_BANK_DEBIT_NOT_CASH_BOOK:
                alerts.append(
                    ComplianceAlert(
                        severity="Action Required",
                        category="Bank debit review",
                        title="Bank debit is not recorded in the cash book",
                        description=(
                            f"{trust_account.name} has a bank debit of ${line.amount} dated {line.line_date} "
                            f"that requires investigation or correction."
                        ),
                        action_url="/trust/reconciliations/"
)
                )
            else:
                alerts.append(
                    ComplianceAlert(
                        severity="Review Required",
                        category="Reconciliation line review",
                        title="Unclassified reconciliation line requires review",
                        description=(
                            f"{trust_account.name} has an unclassified reconciliation line of "
                            f"${line.amount} dated {line.line_date} in the {period_end:%B %Y} reconciliation."
                        ),
                        action_url="/trust/reconciliations/"
)
                )

        return alerts

    def receipt_banking_alerts(self):
        if not self.firm:
            return []

        receipts = (
            Receipt.objects
            .filter(
                transaction__matter_ledger__trust_account__firm=self.firm,
                transaction__is_reversed=False
)
            .select_related(
                "transaction",
                "transaction__matter_ledger",
                "transaction__matter_ledger__matter",
                "transaction__matter_ledger__trust_account"
)
            .order_by("transaction__date_received_or_paid")
        )

        alerts = []

        for receipt in receipts:
            transaction = receipt.transaction
            matter = transaction.matter_ledger.matter
            trust_account = transaction.matter_ledger.trust_account

            if receipt.payment_method in {"cash", "cheque"} and not transaction.date_banked:
                alerts.append(
                    ComplianceAlert(
                        severity="Action Required",
                        category="Banking date missing",
                        title="Cash or cheque receipt has no banking date",
                        description=(
                            f"Receipt #{receipt.receipt_number} for {matter.file_number} was received on "
                            f"{transaction.date_received_or_paid}, but no banking date is recorded."
                        ),
                        action_url="/trust/accounts/",
                        matter=matter
)
                )

            if receipt.late_banking:
                alerts.append(
                    ComplianceAlert(
                        severity="Review Required",
                        category="Late banking",
                        title="Receipt banking timing requires review",
                        description=(
                            f"Receipt #{receipt.receipt_number} for {matter.file_number} was marked for "
                            f"late banking review in {trust_account.name}."
                        ),
                        action_url="/trust/accounts/",
                        matter=matter
)
                )

        return alerts

    def controlled_money_alerts(self):
        if not self.firm:
            return []

        today = timezone.localdate()
        period_end = self.previous_month_end()
        due_date = add_nsw_working_days(period_end, 15)

        alerts = []

        active_accounts = ControlledMoneyAccount.objects.filter(
            firm=self.firm,
            is_active=True,
            opened_on__lte=period_end
).filter(
            Q(current_balance__gt=0) | Q(closed_on__isnull=True)
        )

        if active_accounts.exists():
            statement = ControlledMoneyMonthlyStatement.objects.filter(
                firm=self.firm,
                period_end=period_end
).first()

            if not statement:
                if today > due_date:
                    alerts.append(
                        ComplianceAlert(
                            severity="Action Required",
                            category="Controlled money statement",
                            title="Controlled money monthly statement is overdue",
                            description=(
                                f"A controlled money monthly statement for {period_end:%B %Y} "
                                f"has not been prepared. The due date was {due_date}."
                            ),
                            action_url=reverse("trust:controlled_money_statements")
)
                    )
                elif today > period_end:
                    alerts.append(
                        ComplianceAlert(
                            severity="Reminder",
                            category="Controlled money statement",
                            title="Controlled money monthly statement due",
                            description=(
                                f"A controlled money monthly statement for {period_end:%B %Y} "
                                f"is due by {due_date}."
                            ),
                            action_url=reverse("trust:controlled_money_statements")
)
                    )
            elif not statement.reviewed_on:
                alerts.append(
                    ComplianceAlert(
                        severity="Review Required",
                        category="Controlled money statement",
                        title="Controlled money monthly statement requires review",
                        description=(
                            f"The controlled money monthly statement for {period_end:%B %Y} "
                            f"has been prepared but has not been reviewed."
                        ),
                        action_url=reverse("trust:controlled_money_statement_detail", kwargs={"pk": statement.pk})
)
                )

        for account in ControlledMoneyAccount.objects.filter(firm=self.firm, is_active=True):
            if not account.client_instruction_document:
                alerts.append(
                    ComplianceAlert(
                        severity="Review Required",
                        category="Controlled money authority",
                        title="Controlled money authority document missing",
                        description=(
                            f"{account} is active but no client instruction or authority document is recorded."
                        ),
                        action_url=reverse("trust:controlled_money_detail", kwargs={"pk": account.pk}),
                        matter=account.matter
)
                )

        return alerts

    def statutory_deposit_alerts(self):
        if not self.firm:
            return []

        today = timezone.localdate()
        reminder_cutoff = today + timedelta(days=self.REVIEW_REMINDER_DAYS)
        alerts = []

        trust_accounts = TrustAccount.objects.filter(
            firm=self.firm,
            is_general=True,
            is_active=True
)

        for trust_account in trust_accounts:
            latest = (
                StatutoryDepositRecord.objects
                .filter(trust_account=trust_account)
                .order_by("-applicable_period_end")
                .first()
            )

            if not latest:
                alerts.append(
                    ComplianceAlert(
                        severity="Reminder",
                        category="Statutory deposit",
                        title="Statutory deposit record has not been created",
                        description=(
                            f"{trust_account.name} has no statutory deposit record. "
                            f"Create a record when the statutory deposit position is reviewed."
                        ),
                        action_url=reverse("trust:statutory_deposit_list")
)
                )
                continue

            if latest.adjustment_required and latest.adjustment_required != 0 and not latest.adjustment_made_on:
                if latest.adjustment_due_date and today > latest.adjustment_due_date:
                    severity = "Action Required"
                    title = "Statutory deposit adjustment is overdue"
                    due_text = f"The adjustment due date was {latest.adjustment_due_date}."
                else:
                    severity = "Review Required"
                    title = "Statutory deposit adjustment required"
                    due_text = (
                        f"The adjustment due date is {latest.adjustment_due_date}."
                        if latest.adjustment_due_date else
                        "No adjustment due date has been recorded."
                    )

                alerts.append(
                    ComplianceAlert(
                        severity=severity,
                        category="Statutory deposit",
                        title=title,
                        description=(
                            f"{trust_account.name} has a statutory deposit adjustment of "
                            f"${latest.adjustment_required}. {due_text}"
                        ),
                        action_url=reverse("trust:statutory_deposit_update", kwargs={"pk": latest.pk})
)
                )

            if latest.next_review_due_on:
                if today > latest.next_review_due_on:
                    alerts.append(
                        ComplianceAlert(
                            severity="Review Required",
                            category="Statutory deposit",
                            title="Statutory deposit review is due",
                            description=(
                                f"{trust_account.name} has a statutory deposit review due date of "
                                f"{latest.next_review_due_on}."
                            ),
                            action_url=reverse("trust:statutory_deposit_update", kwargs={"pk": latest.pk})
)
                    )
                elif latest.next_review_due_on <= reminder_cutoff:
                    alerts.append(
                        ComplianceAlert(
                            severity="Reminder",
                            category="Statutory deposit",
                            title="Statutory deposit review due soon",
                            description=(
                                f"{trust_account.name} has a statutory deposit review due by "
                                f"{latest.next_review_due_on}."
                            ),
                            action_url=reverse("trust:statutory_deposit_update", kwargs={"pk": latest.pk})
)
                    )

            missing = []
            if not latest.calculated_on:
                missing.append("calculation date")
            if not latest.supporting_document:
                missing.append("supporting document")
            if not latest.statutory_deposit_adi:
                missing.append("statutory deposit ADI")
            if not latest.statutory_deposit_account_reference:
                missing.append("account reference")

            if missing:
                alerts.append(
                    ComplianceAlert(
                        severity="Review Required",
                        category="Statutory deposit",
                        title="Statutory deposit record is incomplete",
                        description=(
                            f"{trust_account.name} statutory deposit record is missing: "
                            f"{', '.join(missing)}."
                        ),
                        action_url=reverse("trust:statutory_deposit_update", kwargs={"pk": latest.pk})
)
                )

        return alerts

    def investment_alerts(self):
        if not self.firm:
            return []

        today = timezone.localdate()
        reminder_cutoff = today + timedelta(days=self.INVESTMENT_MATURITY_REMINDER_DAYS)
        alerts = []

        filters = Q(matter__firm=self.firm)

        client_model = TrustInvestment._meta.get_field("client").remote_field.model
        if any(field.name == "firm" for field in client_model._meta.fields):
            filters = filters | Q(client__firm=self.firm)

        investments = (
            TrustInvestment.objects
            .filter(filters)
            .filter(repaid_on__isnull=True)
            .select_related("matter", "client")
            .distinct()
        )

        for investment in investments:
            action_url = reverse("trust:investment_detail", kwargs={"pk": investment.pk})

            if not investment.written_direction_date and not investment.written_direction_document:
                alerts.append(
                    ComplianceAlert(
                        severity="Action Required",
                        category="Trust investment",
                        title="Investment written direction missing",
                        description=(
                            f"The trust investment for {investment.person_on_behalf} "
                            f"does not have a written direction date or written direction document recorded."
                        ),
                        action_url=action_url,
                        matter=investment.matter
)
                )

            if not investment.evidence_document:
                alerts.append(
                    ComplianceAlert(
                        severity="Review Required",
                        category="Trust investment",
                        title="Investment evidence document missing",
                        description=(
                            f"The trust investment for {investment.person_on_behalf} "
                            f"does not have an evidence document recorded."
                        ),
                        action_url=action_url,
                        matter=investment.matter
)
                )

            if not investment.maturity_due_on:
                alerts.append(
                    ComplianceAlert(
                        severity="Reminder",
                        category="Trust investment",
                        title="Investment maturity date missing",
                        description=(
                            f"The trust investment for {investment.person_on_behalf} "
                            f"does not have a maturity due date recorded."
                        ),
                        action_url=action_url,
                        matter=investment.matter
)
                )
            elif investment.maturity_due_on < today:
                alerts.append(
                    ComplianceAlert(
                        severity="Action Required",
                        category="Trust investment",
                        title="Investment maturity is overdue",
                        description=(
                            f"The trust investment for {investment.person_on_behalf} "
                            f"matured on {investment.maturity_due_on} and has not been marked as repaid."
                        ),
                        action_url=action_url,
                        matter=investment.matter
)
                )

                if not investment.maturity_repayment_details:
                    alerts.append(
                        ComplianceAlert(
                            severity="Review Required",
                            category="Trust investment",
                            title="Investment repayment details missing",
                            description=(
                                f"The trust investment for {investment.person_on_behalf} "
                                f"has matured but repayment details have not been recorded."
                            ),
                            action_url=action_url,
                            matter=investment.matter
)
                    )

            elif investment.maturity_due_on <= reminder_cutoff:
                alerts.append(
                    ComplianceAlert(
                        severity="Reminder",
                        category="Trust investment",
                        title="Investment maturity approaching",
                        description=(
                            f"The trust investment for {investment.person_on_behalf} "
                            f"matures on {investment.maturity_due_on}."
                        ),
                        action_url=action_url,
                        matter=investment.matter
)
                )

        return alerts

    def authorised_signatory_alerts(self):
        if not self.firm:
            return []

        today = timezone.localdate()
        reminder_cutoff = today + timedelta(days=self.SIGNATORY_REVIEW_REMINDER_DAYS)
        alerts = []

        trust_accounts = TrustAccount.objects.filter(
            firm=self.firm,
            is_active=True,
            is_general=True
)

        for trust_account in trust_accounts:
            active_signatories = AuthorisedSignatory.objects.filter(
                trust_account=trust_account,
                is_active=True
)

            if not active_signatories.exists():
                alerts.append(
                    ComplianceAlert(
                        severity="Action Required",
                        category="Authorised signatory",
                        title="No active authorised signatory recorded",
                        description=(
                            f"{trust_account.name} is active but has no active authorised signatory recorded."
                        ),
                        action_url=reverse("trust:authorised_signatory_list")
)
                )
                continue

            payment_authorised = active_signatories.filter(
                Q(authorised_trust_cheques=True) | Q(authorised_trust_efts=True)
            ).exists()

            if not payment_authorised:
                alerts.append(
                    ComplianceAlert(
                        severity="Review Required",
                        category="Authorised signatory",
                        title="No active payment signatory recorded",
                        description=(
                            f"{trust_account.name} has active signatories, but none are authorised "
                            f"for trust cheques or trust EFTs."
                        ),
                        action_url=reverse("trust:authorised_signatory_list")
)
                )

        signatories = (
            AuthorisedSignatory.objects
            .filter(trust_account__firm=self.firm, is_active=True)
            .select_related("trust_account")
        )

        for signatory in signatories:
            action_url = reverse("trust:authorised_signatory_update", kwargs={"pk": signatory.pk})

            if signatory.authorised_to and signatory.authorised_to < today:
                alerts.append(
                    ComplianceAlert(
                        severity="Action Required",
                        category="Authorised signatory",
                        title="Authorised signatory authority has expired",
                        description=(
                            f"{signatory.name} remains active for {signatory.trust_account.name}, "
                            f"but the authorisation ended on {signatory.authorised_to}."
                        ),
                        action_url=action_url
)
                )

            if not signatory.next_review_due_on:
                alerts.append(
                    ComplianceAlert(
                        severity="Reminder",
                        category="Authorised signatory",
                        title="Authorised signatory review date not set",
                        description=(
                            f"{signatory.name} is active for {signatory.trust_account.name}, "
                            f"but no next review due date has been recorded."
                        ),
                        action_url=action_url
)
                )
            elif signatory.next_review_due_on < today:
                alerts.append(
                    ComplianceAlert(
                        severity="Review Required",
                        category="Authorised signatory",
                        title="Authorised signatory review is overdue",
                        description=(
                            f"{signatory.name} was due for review on {signatory.next_review_due_on}."
                        ),
                        action_url=action_url
)
                )
            elif signatory.next_review_due_on <= reminder_cutoff:
                alerts.append(
                    ComplianceAlert(
                        severity="Reminder",
                        category="Authorised signatory",
                        title="Authorised signatory review due soon",
                        description=(
                            f"{signatory.name} is due for review on {signatory.next_review_due_on}."
                        ),
                        action_url=action_url
)
                )

            if signatory.role in {"principal", "solicitor"} and not signatory.practising_certificate_number:
                alerts.append(
                    ComplianceAlert(
                        severity="Review Required",
                        category="Authorised signatory",
                        title="Practising certificate number missing",
                        description=(
                            f"{signatory.name} is recorded as {signatory.get_role_display()} "
                            f"but no practising certificate number has been recorded."
                        ),
                        action_url=action_url
)
                )

        return alerts

    def written_direction_alerts(self):
        if not self.firm:
            return []

        alerts = []
        filters = Q(matter__firm=self.firm)

        client_model = WrittenDirection._meta.get_field("client").remote_field.model
        if any(field.name == "firm" for field in client_model._meta.fields):
            filters = filters | Q(client__firm=self.firm)

        directions = (
            WrittenDirection.objects
            .filter(filters)
            .select_related("client", "matter", "linked_transaction")
            .distinct()
        )

        for direction in directions:
            action_url = reverse("trust:written_direction_update", kwargs={"pk": direction.pk})

            if not direction.document:
                alerts.append(
                    ComplianceAlert(
                        severity="Action Required",
                        category="Written direction",
                        title="Written direction document missing",
                        description=(
                            f"The written direction for {direction.client} dated {direction.signed_on} "
                            f"does not have a document attached."
                        ),
                        action_url=action_url,
                        matter=direction.matter
)
                )

            if not direction.direction_text or len(direction.direction_text.strip()) < 10:
                alerts.append(
                    ComplianceAlert(
                        severity="Review Required",
                        category="Written direction",
                        title="Written direction details incomplete",
                        description=(
                            f"The written direction for {direction.client} dated {direction.signed_on} "
                            f"has limited direction details recorded."
                        ),
                        action_url=action_url,
                        matter=direction.matter
)
                )

            if not direction.matter and not direction.linked_transaction:
                alerts.append(
                    ComplianceAlert(
                        severity="Review Required",
                        category="Written direction",
                        title="Written direction is not linked",
                        description=(
                            f"The written direction for {direction.client} dated {direction.signed_on} "
                            f"is not linked to a matter or trust transaction."
                        ),
                        action_url=action_url,
                        matter=direction.matter
)
                )

            if direction.signed_on and direction.signed_on > timezone.localdate():
                alerts.append(
                    ComplianceAlert(
                        severity="Action Required",
                        category="Written direction",
                        title="Written direction is future dated",
                        description=(
                            f"The written direction for {direction.client} has a signed date of "
                            f"{direction.signed_on}."
                        ),
                        action_url=action_url,
                        matter=direction.matter
)
                )

        return alerts

    def transit_money_alerts(self):
        if not self.firm:
            return []

        today = timezone.localdate()
        alerts = []

        filters = Q(matter__firm=self.firm)

        client_model = TransitMoneyEntry._meta.get_field("client").remote_field.model
        if any(field.name == "firm" for field in client_model._meta.fields):
            filters = filters | Q(client__firm=self.firm)

        entries = (
            TransitMoneyEntry.objects
            .filter(filters)
            .select_related("client", "matter")
            .distinct()
        )

        for entry in entries:
            action_url = reverse("trust:transit_money_update", kwargs={"pk": entry.pk})

            if not entry.instructions_document:
                alerts.append(
                    ComplianceAlert(
                        severity="Review Required",
                        category="Transit money",
                        title="Transit money instructions missing",
                        description=(
                            f"Transit money of ${entry.amount} received from {entry.payor} "
                            f"does not have written instructions attached."
                        ),
                        action_url=action_url,
                        matter=entry.matter
)
                )

            if not entry.paid_on:
                days_pending = (today - entry.received_on).days

                if days_pending > self.TRANSIT_MONEY_PENDING_DAYS:
                    alerts.append(
                        ComplianceAlert(
                            severity="Action Required",
                            category="Transit money",
                            title="Transit money has not been paid out",
                            description=(
                                f"Transit money of ${entry.amount} received from {entry.payor} "
                                f"on {entry.received_on} remains pending after {days_pending} days."
                            ),
                            action_url=action_url,
                            matter=entry.matter
)
                    )
                else:
                    alerts.append(
                        ComplianceAlert(
                            severity="Reminder",
                            category="Transit money",
                            title="Transit money pending",
                            description=(
                                f"Transit money of ${entry.amount} received from {entry.payor} "
                                f"on {entry.received_on} has not yet been marked as paid out."
                            ),
                            action_url=action_url,
                            matter=entry.matter
)
                    )

            elif not entry.supporting_document:
                alerts.append(
                    ComplianceAlert(
                        severity="Review Required",
                        category="Transit money",
                        title="Transit money supporting document missing",
                        description=(
                            f"Transit money of ${entry.amount} received from {entry.payor} "
                            f"was paid out on {entry.paid_on}, but no supporting document is attached."
                        ),
                        action_url=action_url,
                        matter=entry.matter
)
                )

        return alerts

    def power_money_alerts(self):
        if not self.firm:
            return []

        alerts = []
        filters = Q(matter__firm=self.firm)

        client_model = PowerMoneyEntry._meta.get_field("client").remote_field.model
        if any(field.name == "firm" for field in client_model._meta.fields):
            filters = filters | Q(client__firm=self.firm)

        entries = (
            PowerMoneyEntry.objects
            .filter(filters)
            .select_related("client", "matter")
            .distinct()
        )

        for entry in entries:
            action_url = reverse("trust:power_money_update", kwargs={"pk": entry.pk})

            if entry.amount_held and entry.amount_held > 0 and not entry.power_instrument and not entry.authority_document:
                alerts.append(
                    ComplianceAlert(
                        severity="Action Required",
                        category="Powers and estates",
                        title="Authority document missing for money held",
                        description=(
                            f"{entry} records ${entry.amount_held} held, but no power instrument "
                            f"or authority document is attached."
                        ),
                        action_url=action_url,
                        matter=entry.matter
)
                )

            if entry.amount_held and entry.amount_held > 0 and not entry.responsible_solicitor:
                alerts.append(
                    ComplianceAlert(
                        severity="Review Required",
                        category="Powers and estates",
                        title="Responsible solicitor not recorded",
                        description=(
                            f"{entry} records ${entry.amount_held} held, but no responsible solicitor "
                            f"has been recorded."
                        ),
                        action_url=action_url,
                        matter=entry.matter
)
                )

            if entry.amount_held and entry.amount_held > 0 and not entry.dealings.exists():
                alerts.append(
                    ComplianceAlert(
                        severity="Reminder",
                        category="Powers and estates",
                        title="No dealings recorded for money held",
                        description=(
                            f"{entry} records ${entry.amount_held} held, but no power/estate dealings "
                            f"have been recorded."
                        ),
                        action_url=reverse("trust:power_money_detail", kwargs={"pk": entry.pk}),
                        matter=entry.matter
)
                )

        dealings = (
            PowerMoneyDealing.objects
            .filter(power_entry__in=entries)
            .select_related("power_entry", "power_entry__matter")
        )

        for dealing in dealings:
            if (dealing.deposit or dealing.withdrawal) and not dealing.supporting_document:
                alerts.append(
                    ComplianceAlert(
                        severity="Review Required",
                        category="Powers and estates",
                        title="Power or estate dealing support missing",
                        description=(
                            f"A power/estate dealing dated {dealing.dealing_date} for {dealing.power_entry} "
                            f"does not have a supporting document attached."
                        ),
                        action_url=reverse("trust:power_money_detail", kwargs={"pk": dealing.power_entry.pk}),
                        matter=dealing.power_entry.matter
)
                )

        return alerts


    def unclaimed_money_alerts(self):
        if not self.firm:
            return []

        unresolved_statuses = [
            UnclaimedMoneyRecord.STATUS_UNDER_REVIEW,
            UnclaimedMoneyRecord.STATUS_CLIENT_CONTACTED,
        ]

        records = (
            UnclaimedMoneyRecord.objects
            .filter(firm=self.firm, status__in=unresolved_statuses)
            .select_related("matter_ledger", "matter_ledger__matter", "trust_account")
        )

        alerts = []

        for record in records:
            if not record.reviewed_on:
                severity = "Review Required"
                title = "Unclaimed money record not reviewed"
            else:
                severity = "Reminder"
                title = "Unclaimed money record remains open"

            alerts.append(
                ComplianceAlert(
                    severity=severity,
                    category="Unclaimed money",
                    title=title,
                    description=(
                        f"{record.matter_ledger.matter.file_number} has an unclaimed money review "
                        f"record for ${record.amount} with status {record.get_status_display()}."
                    ),
                    action_url=reverse("trust:unclaimed_money_update", kwargs={"pk": record.pk}),
                    matter=record.matter_ledger.matter
)
            )

        return alerts

    def old_trust_balance_alerts(self):
        if not self.firm:
            return []

        cutoff = timezone.localdate() - timedelta(days=self.OLD_BALANCE_DAYS)

        ledgers = (
            MatterLedger.objects
            .filter(
                trust_account__firm=self.firm,
                balance__gt=0,
                matter__status="open"
)
            .select_related("matter", "trust_account", "matter__client")
            .annotate(last_activity=Max("transactions__date_received_or_paid"))
        )

        alerts = []

        for ledger in ledgers:
            last_activity = ledger.last_activity

            if not last_activity:
                opened_on = ledger.matter.opened_on
                if hasattr(opened_on, "date"):
                    opened_on = opened_on.date()
                last_activity = opened_on

            if last_activity and last_activity <= cutoff:
                days_old = (timezone.localdate() - last_activity).days
                alerts.append(
                    ComplianceAlert(
                        severity="Review Required",
                        category="Old trust balance",
                        title=f"Trust balance requires review after {days_old} days",
                        description=(
                            f"{ledger.matter.file_number} has a trust balance of "
                            f"${ledger.balance} with no trust activity since {last_activity}."
                        ),
                        action_url=reverse("matters:matter_detail", kwargs={"pk": ledger.matter.pk}),
                        matter=ledger.matter
)
                )

        return alerts
