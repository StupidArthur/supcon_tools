"""UA-2 create scenarios."""
from ua_test_harness.assertions import check_true
from ua_test_harness.ua2_common import create_read_tag, prepare_datasource, wait_rt


def create_and_read(ctx, cc):
    ds = prepare_datasource(ctx, cc)
    name = "ua_auto_ua2_create_read"
    create_read_tag(ctx, cc, ds["id"], name=name)
    row = wait_rt(ctx, name)
    check_true("ua2_rt_value", row is not None)


def create_unique_name(ctx, cc):
    ds = prepare_datasource(ctx, cc)
    create_read_tag(ctx, cc, ds["id"], name="ua_auto_same_name")
    try:
        create_read_tag(ctx, cc, ds["id"], name="ua_auto_same_name")
    except Exception:
        return
    raise AssertionError("duplicate tag name accepted")
