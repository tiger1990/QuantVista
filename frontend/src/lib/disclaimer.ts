/**
 * The single source of the non-advice line in the frontend.
 *
 * It must stay identical to the API's `DISCLAIMER` (`api/routes_stocks.py`), which ships in every
 * research response's `meta.disclaimer` and in the `X-QuantVista-Disclaimer` header. Two copies of
 * a compliance string is one copy too many — `backend/tests/test_methodology_constants.py` fails
 * the build if this drifts from the Python constant. See `plans/07-security-and-compliance.md` §1.
 */
export const DISCLAIMER = "Research signal, not investment advice.";
