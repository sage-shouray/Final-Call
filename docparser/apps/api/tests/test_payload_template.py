"""Per-tenant payload shaping.

The template is what lets a new customer be onboarded by configuration rather
than a code change, so the cases below are the ones that decide whether their
SAP accepts the posting: types, nesting, repeated line items, and constants.
"""
import pytest

from src.services.payload_template import TemplateError, placeholders, render


def test_whole_string_placeholder_keeps_its_type():
    """SAP rejects "1000.00" where it expects a number, so a placeholder that is
    the entire string must not stringify what it substitutes."""
    out, missing = render({"amount": "{{gross_amount}}"}, {"gross_amount": 702100.0})

    assert out == {"amount": 702100.0}
    assert isinstance(out["amount"], float)
    assert missing == []


def test_embedded_placeholder_becomes_text():
    out, _ = render({"ref": "PO-{{po_number}}/2026"}, {"po_number": "4500022773"})
    assert out == {"ref": "PO-4500022773/2026"}


def test_dotted_paths_walk_nested_context():
    out, _ = render(
        {"cc": "{{header.company_code}}"},
        {"header": {"company_code": "SSDN"}},
    )
    assert out == {"cc": "SSDN"}


def test_constants_pass_through_untouched():
    """Customer-specific constants (tax indicators, plant codes) belong in the
    template, not in code."""
    out, _ = render(
        {"calc_tax_ind": "X", "plant": "SSDN", "retries": 3, "flag": True},
        {},
    )
    assert out == {"calc_tax_ind": "X", "plant": "SSDN", "retries": 3, "flag": True}


def test_line_items_expand_once_per_row():
    template = {
        "data": [{
            "item_data": [{
                "__repeat__": "line_items",
                "po_item": "{{item.line_number}}",
                "amount": "{{item.amount}}",
                "tax_code": "V0",
            }],
        }],
    }
    context = {"line_items": [
        {"line_number": "00010", "amount": 495000.0},
        {"line_number": "00020", "amount": 100000.0},
    ]}

    out, missing = render(template, context)

    assert out["data"][0]["item_data"] == [
        {"po_item": "00010", "amount": 495000.0, "tax_code": "V0"},
        {"po_item": "00020", "amount": 100000.0, "tax_code": "V0"},
    ]
    assert missing == []


def test_empty_line_items_produce_an_empty_array():
    template = {"items": [{"__repeat__": "line_items", "x": "{{item.a}}"}]}
    out, _ = render(template, {"line_items": []})
    assert out == {"items": []}


def test_repeating_a_non_list_is_a_template_error():
    with pytest.raises(TemplateError):
        render({"items": [{"__repeat__": "vendor_name", "x": "{{item.a}}"}]},
               {"vendor_name": "Sage"})


def test_missing_fields_are_reported_not_raised():
    """A customer template may reference a field this document does not carry.
    That must surface as an explicit gap, not abort the posting."""
    out, missing = render(
        {"a": "{{present}}", "b": "{{absent}}"},
        {"present": "yes"},
    )

    assert out == {"a": "yes", "b": None}
    assert missing == ["absent"]


def test_missing_nested_path_does_not_explode():
    out, missing = render({"x": "{{a.b.c}}"}, {"a": {}})
    assert out == {"x": None}
    assert missing == ["a.b.c"]


def test_two_customers_get_different_shapes_from_one_document():
    """The point of the whole mechanism."""
    document = {
        "po_number": "4500022773",
        "gross_amount": 702100.0,
        "company_code": "SSDN",
        "line_items": [{"line_number": "00010", "amount": 495000.0}],
    }

    customer_a = {
        "data": [{
            "reference_document_no": "{{po_number}}",
            "company_code": "{{company_code}}",
            "gross_amount": "{{gross_amount}}",
            "item_data": [{"__repeat__": "line_items", "po_item": "{{item.line_number}}"}],
        }],
    }
    customer_b = {
        "Header": {"PONumber": "{{po_number}}", "Total": "{{gross_amount}}", "Bukrs": "{{company_code}}"},
        "Lines": [{"__repeat__": "line_items", "Item": "{{item.line_number}}", "Amt": "{{item.amount}}"}],
    }

    a, _ = render(customer_a, document)
    b, _ = render(customer_b, document)

    assert a["data"][0]["reference_document_no"] == "4500022773"
    assert a["data"][0]["item_data"] == [{"po_item": "00010"}]
    assert b["Header"] == {"PONumber": "4500022773", "Total": 702100.0, "Bukrs": "SSDN"}
    assert b["Lines"] == [{"Item": "00010", "Amt": 495000.0}]


def test_placeholders_lists_what_a_template_needs():
    """Used to validate a pasted template before it is saved, so a typo is
    caught in the admin panel rather than at posting time."""
    template = {
        "a": "{{po_number}}",
        "b": "text {{vendor_name}} more",
        "c": [{"__repeat__": "line_items", "d": "{{item.amount}}"}],
    }
    assert placeholders(template) == {"po_number", "vendor_name", "line_items", "item.amount"}
