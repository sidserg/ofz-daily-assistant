import os
import sys
from decimal import Decimal
from t_tech.invest import Client, RequestError, InstrumentIdType
from t_tech.invest.utils import quotation_to_decimal
from t_tech.invest.schemas import OrderDirection, OrderType

MIN_THRESHOLD_RUB = 600.0
COUPON_NKD_LIMIT_RATIO = 0.5

def quotation_to_float(q) -> float:
    return float(quotation_to_decimal(q))

def get_free_rub(client, account_id: str) -> float:
    try:
        limits = client.operations.get_withdraw_limits(account_id=account_id)
        for money in limits.money:
            if money.currency == "rub":
                return quotation_to_float(money)
        return 0.0
    except RequestError as e:
        print(f"Ошибка получения лимитов: {e}")
        return 0.0

def get_bonds_in_portfolio(client, account_id: str) -> list:
    try:
        portfolio = client.operations.get_portfolio(account_id=account_id)
        bonds = []
        for pos in portfolio.positions:
            if pos.instrument_type == "bond":
                # Получаем номинал облигации через BondBy
                bond = client.instruments.bond_by(
                    id_type=InstrumentIdType.INSTRUMENT_ID_TYPE_FIGI,
                    id=pos.figi
                ).instrument
                nominal = quotation_to_float(bond.nominal)
                # Цена в пунктах -> рубли: price / 100 * nominal
                price_rub = quotation_to_float(pos.current_price) / 100.0 * nominal
                bonds.append({
                    "figi": pos.figi,
                    "instrument_uid": pos.instrument_uid,
                    "quantity": quotation_to_float(pos.quantity),
                    "current_nkd": quotation_to_float(pos.current_nkd) if pos.current_nkd else 0.0,
                    "current_price": price_rub,
                })
        return bonds
    except RequestError as e:
        print(f"Ошибка получения портфеля: {e}")
        return []

def get_bond_details(client, figi: str):
    try:
        bond = client.instruments.bond_by(
            id_type=InstrumentIdType.INSTRUMENT_ID_TYPE_FIGI,
            id=figi
        ).instrument
        return {
            "figi": bond.figi,
            "ticker": bond.ticker,
            "name": bond.name,
            "nominal": quotation_to_float(bond.nominal),
            "coupon_quantity_per_year": bond.coupon_quantity_per_year,
            "aci_value": quotation_to_float(bond.aci_value) if bond.aci_value else 0.0,
            "maturity_date": bond.maturity_date,
        }
    except RequestError as e:
        print(f"Ошибка получения данных облигации {figi}: {e}")
        return None

def calculate_coupon_per_period(bond_info) -> float:
    return 0.0

def select_bond_to_buy(client, bonds: list) -> dict:
    candidates = []
    for b in bonds:
        details = get_bond_details(client, b["figi"])
        if not details:
            continue
        nkd = details["aci_value"] if details["aci_value"] > 0 else b["current_nkd"]
        coupon = calculate_coupon_per_period(details)
        if coupon > 0 and nkd > coupon * COUPON_NKD_LIMIT_RATIO:
            print(f"Пропуск {details['ticker']}: НКД ({nkd:.2f}) > 50% купона ({coupon:.2f})")
            continue
        candidates.append({**b, **details, "nkd": nkd})
    if not candidates:
        return None
    candidates.sort(key=lambda x: x["nkd"])
    return candidates[0]

def calculate_buy_quantity(free_rub: float, bond: dict) -> int:
    price_pct = bond["current_price"]
    nominal = bond["nominal"]
    nkd = bond["nkd"]
    lot_price_rub = (price_pct / 100.0) * nominal + nkd
    if lot_price_rub <= 0:
        return 0
    quantity = int(free_rub // lot_price_rub)
    print(f"Цена лота (с НКД): {lot_price_rub:.2f} руб. Доступно: {free_rub:.2f} руб. Можно купить: {quantity} лотов")
    return quantity

def main():
    token = os.environ.get("TINKOFF_TOKEN")
    if not token:
        print("Ошибка: TINKOFF_TOKEN не найден")
        sys.exit(1)

    try:
        with Client(token) as client:
            accounts = client.users.get_accounts().accounts
            if not accounts:
                print("Нет доступных счетов")
                return
            account_id = accounts[0].id
            print(f"Используем счёт: {account_id}")

            free_rub = get_free_rub(client, account_id)
            print(f"Свободных рублей: {free_rub:.2f}")

            if free_rub < MIN_THRESHOLD_RUB:
                print(f"Сумма меньше порога {MIN_THRESHOLD_RUB} руб. Завершаем.")
                return

            bonds = get_bonds_in_portfolio(client, account_id)
            if not bonds:
                print("В портфеле нет облигаций.")
                return
            print(f"Найдено облигаций в портфеле: {len(bonds)}")

            selected = select_bond_to_buy(client, bonds)
            if not selected:
                print("Нет подходящих ОФЗ для покупки (все отфильтрованы).")
                return
            print(f"Выбрана ОФЗ: {selected['ticker']} ({selected['name']}), НКД: {selected['nkd']:.2f}")

            quantity = calculate_buy_quantity(free_rub, selected)
            if quantity <= 0:
                print("Недостаточно средств для покупки даже 1 лота.")
                return

            print(f"Выставляем заявку на покупку {quantity} лотов {selected['ticker']}...")
            try:
                response = client.orders.post_order(
                    instrument_id=selected["instrument_uid"],
                    quantity=quantity,
                    direction=OrderDirection.ORDER_DIRECTION_BUY,
                    account_id=account_id,
                    order_type=OrderType.ORDER_TYPE_MARKET,
                )
                print(f"Заявка выставлена: {response.order_id}, статус: {response.execution_report_status}")
            except RequestError as e:
                print(f"Ошибка выставления заявки: {e}")
    except RequestError as e:
        print(f"Ошибка API: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
