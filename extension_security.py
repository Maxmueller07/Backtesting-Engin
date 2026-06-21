from indicator_registry import FormulaSecurityAuditor


def audit_formula_indicator(indicator_definition):
    return FormulaSecurityAuditor.audit(indicator_definition)


__all__ = ["FormulaSecurityAuditor", "audit_formula_indicator"]

