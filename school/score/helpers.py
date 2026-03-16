# # helpers.py

# # helpers.py

# class ScoreHelper:

#     # -------------------------
#     # Display helper
#     # -------------------------
#     @staticmethod
#     def ordinal(n):
#         """Convert number to ordinal (1 -> 1st, 2 -> 2nd, etc.)"""
#         if not n:
#             return ""
#         if 10 <= n % 100 <= 20:
#             suffix = "th"
#         else:
#             suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
#         return f"{n}{suffix}"

#     # -------------------------
#     # SHARED ranking & statistics
#     # -------------------------
#     @staticmethod
#     def _update_ranking_and_stats(scores):
#         """
#         Shared logic for:
#         - average
#         - highest
#         - lowest
#         - position
#         - grade & remark
#         """
#         totals = list(scores.values_list('total', flat=True))
#         if not totals:
#             return

#         max_score = max(totals)
#         min_score = min(totals)
#         avg_score = round(sum(totals) / len(totals), 2)

#         last_total = None
#         position = 0
#         counter = 0

#         for score in scores:
#             counter += 1
#             if score.total != last_total:
#                 position = counter

#             score.max_score = max_score
#             score.min_score = min_score
#             score.avg_score = avg_score
#             score.position = position

#             # Grade & remark
#             if score.total >= 70:
#                 score.grade = "A"
#                 score.remark = "Excellent"
#             elif score.total >= 60:
#                 score.grade = "B"
#                 score.remark = "Very Good"
#             elif score.total >= 50:
#                 score.grade = "C"
#                 score.remark = "Good"
#             elif score.total >= 45:
#                 score.grade = "D"
#                 score.remark = "Fair"
#             else:
#                 score.grade = "F"
#                 score.remark = "Needs Improvement"

#             score.save(update_fields=[
#                 'max_score', 'min_score', 'avg_score',
#                 'position', 'grade', 'remark'
#             ])

#             last_total = score.total

#     # -------------------------
#     # DEFAULT grading system
#     # -------------------------
#     @staticmethod
#     def update_scores(subject, term=None, session=None):
#         """
#         Recalculate ranking + stats for DEFAULT grading system.
#         Assumes `total` is already calculated.
#         """
#         from .models import Score

#         qs = Score.objects.filter(subject=subject)
#         if term:
#             qs = qs.filter(term=term)
#         if session:
#             qs = qs.filter(session=session)

#         ScoreHelper._update_ranking_and_stats(qs.order_by('-total'))

#     # -------------------------
#     # CUSTOM grading system
#     # -------------------------
#     @staticmethod
#     def update_custom_totals(subject, term, session):
#         """
#         Calculate TOTAL using custom components,
#         then apply shared ranking/stat logic.
#         """
#         from .models import Score

#         scores = Score.objects.filter(
#             subject=subject,
#             term=term,
#             session=session
#         ).select_related('student__class_group__custom_scoring_system')

#         # 1️⃣ Calculate TOTAL (custom grading)
#         for score in scores:
#             class_group = score.student.class_group
#             custom_system = getattr(class_group, 'custom_scoring_system', None)

#             if (
#                 class_group.scoring_system == 'custom' and
#                 custom_system and
#                 custom_system.components
#             ):
#                 data = score.custom_scores or {}
#                 total = sum(float(v) for v in data.values())
#                 score.total = round(total, 2)
#                 score.save(update_fields=['total'])

#         # 2️⃣ Shared ranking/stat logic
#         ScoreHelper._update_ranking_and_stats(scores.order_by('-total'))


# def is_result_published(term, session):
#     from .models import PublishedResult
#     return PublishedResult.objects.filter(term=term, session=session, is_published=True).exists()


# helpers.py

class ScoreHelper:

    # -------------------------
    # Display helper
    # -------------------------
    @staticmethod
    def ordinal(n):
        """Convert number to ordinal (1 -> 1st, 2 -> 2nd, etc.)"""
        if not n:
            return ""
        if 10 <= n % 100 <= 20:
            suffix = "th"
        else:
            suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
        return f"{n}{suffix}"

    # -------------------------
    # SHARED ranking & statistics
    # -------------------------
    @staticmethod
    def _update_ranking_and_stats(scores):
        """
        Shared logic for:
        - average
        - highest
        - lowest
        - position
        Note: Grade & remark are now handled in the Score model's save() method
        """
        totals = list(scores.values_list('total', flat=True))
        if not totals:
            return

        max_score = max(totals)
        min_score = min(totals)
        avg_score = round(sum(totals) / len(totals), 2)

        last_total = None
        position = 0
        counter = 0

        for score in scores:
            counter += 1
            if score.total != last_total:
                position = counter

            score.max_score = max_score
            score.min_score = min_score
            score.avg_score = avg_score
            score.position = position
            score.ordinal_position = ScoreHelper.ordinal(position)

            # Save with specific fields to avoid triggering full recalculation
            score.save(update_fields=[
                'max_score', 'min_score', 'avg_score',
                'position', 'ordinal_position'
            ])

            last_total = score.total

    # -------------------------
    # DEFAULT grading system
    # -------------------------
    @staticmethod
    def update_scores(subject, term=None, session=None):
        """
        Recalculate ranking + stats for DEFAULT grading system.
        Assumes `total` is already calculated by the model's save() method.
        """
        from .models import Score

        qs = Score.objects.filter(subject=subject)
        if term:
            qs = qs.filter(term=term)
        if session:
            qs = qs.filter(session=session)

        ScoreHelper._update_ranking_and_stats(qs.order_by('-total'))

    # -------------------------
    # CUSTOM grading system
    # -------------------------
    @staticmethod
    def update_custom_totals(subject, term, session):
        """
        Update ranking and statistics for custom grading system.
        Total is already calculated by the Score model's save() method,
        so we just need to update positions and stats.
        """
        from .models import Score

        scores = Score.objects.filter(
            subject=subject,
            term=term,
            session=session
        ).order_by('-total')

        # Apply shared ranking/stat logic
        # The totals are already calculated by the model's save() method
        ScoreHelper._update_ranking_and_stats(scores)


def is_result_published(term, session):
    from .models import PublishedResult
    return PublishedResult.objects.filter(
        term=term, 
        session=session, 
        is_published=True
    ).exists()



# helpers.py — ADD THIS FUNCTION



# def prepare_dynamic_report_data(student, academic_session, term_obj, scores):
#     from .models import Score, ScoreHelper
#     """
#     Prepares data for dynamic report card columns.
#     Used by reportcard_view_context and all bulk views.
#     Adds:
#         - assessment_components (list of dicts: name, percentage, key)
#         - scores_dict on each Score object (for template lookup)
#         - ordinal_position (already calculated elsewhere, but ensured here)
#     Returns: (updated_scores, assessment_components)
#     """
#     scoring_scheme = student.class_group.scoring_system

#     # Predefined schemes
#     SCHEMES = {
#         'scheme_1': [
#             {'name': 'CA1', 'percentage': 20, 'key': 'ca1'},
#             {'name': 'CA2', 'percentage': 20, 'key': 'ca2'},
#             {'name': 'CA3', 'percentage': 20, 'key': 'ca3'},
#             {'name': 'Exam', 'percentage': 40, 'key': 'exam'},
#         ],
#         'scheme_2': [
#             {'name': 'CA1', 'percentage': 20, 'key': 'ca1'},
#             {'name': 'CA2', 'percentage': 10, 'key': 'ca2'},
#             {'name': 'CA3', 'percentage': 10, 'key': 'ca3'},
#             {'name': 'Exam', 'percentage': 60, 'key': 'exam'},
#         ],
#         'scheme_3': [
#             {'name': 'CA1', 'percentage': 20, 'key': 'ca1'},
#             {'name': 'CA2', 'percentage': 15, 'key': 'ca2'},
#             {'name': 'CA3', 'percentage': 15, 'key': 'ca3'},
#             {'name': 'Exam', 'percentage': 50, 'key': 'exam'},
#         ],
#         'scheme_4': [
#             {'name': 'CA1', 'percentage': 10, 'key': 'ca1'},
#             {'name': 'CA2', 'percentage': 10, 'key': 'ca2'},
#             {'name': 'CA3', 'percentage': 10, 'key': 'ca3'},
#             {'name': 'Exam', 'percentage': 70, 'key': 'exam'},
#         ],
#     }

#     if scoring_scheme == 'custom':
#         try:
#             custom_system = student.class_group.custom_scoring_system
#             if custom_system.is_configured():
#                 assessment_components = [
#                     {'name': name, 'percentage': int(pct), 'key': name.lower().replace(' ', '_')}
#                     for name, pct in custom_system.components.items()
#                     if pct > 0
#                 ]
#             else:
#                 assessment_components = SCHEMES['scheme_1']
#         except AttributeError:
#             assessment_components = SCHEMES['scheme_1']
#     else:
#         assessment_components = SCHEMES.get(scoring_scheme, SCHEMES['scheme_1'])

#     # Ensure positions are set (in case called independently)
#     positions_map = {}
#     for subject in {s.subject for s in scores}:
#         subject_scores = Score.objects.filter(
#             subject=subject,
#             student__class_group=student.class_group,
#             session=academic_session,
#             term=term_obj
#         ).order_by("-total")
#         for idx, sc in enumerate(subject_scores, start=1):
#             positions_map[sc.id] = ScoreHelper.ordinal(idx)

#     # Attach scores_dict and ensure position
#     for s in scores:
#         s.ordinal_position = positions_map.get(s.id, "—")

#         s.scores_dict = {}

#         if scoring_scheme == 'custom' and s.custom_scores:
#             for name, value in s.custom_scores.items():
#                 key = name.lower().replace(' ', '_')
#                 s.scores_dict[key] = value
#         else:
#             s.scores_dict.update({
#                 'ca1': s.ca1 or None,
#                 'ca2': s.ca2 or None,
#                 'ca3': s.ca3 or None,
#                 'exam': s.exam or None,
#             })

#         # Ensure all components exist in scores_dict (template will show "-" if None)
#         for comp in assessment_components:
#             if comp['key'] not in s.scores_dict:
#                 s.scores_dict[comp['key']] = None

#     return scores, assessment_components