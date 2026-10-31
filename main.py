import warnings
warnings.filterwarnings('ignore', category=DeprecationWarning)
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
                bond = client.instruments.bond_by(
                    id_type=InstrumentIdType.INSTRUMENT_ID_TYPE_FIGI,
                    id=pos.figi,
                ).instrument
                
                # Фильтр: только ОФЗ (класс TQOB)
                if bond.class_code != "TQOB":
                    print(f"  Пропуск {bond.ticker}: это не ОФЗ (класс {bond.class_code})")
                    continue
                
                # API отдает цену в рублях
                price_rub = quotation_to_float(pos.current_price)
                nkd = quotation_to_float(pos.current_nkd) if pos.current_nkd else 0.0
                lot_price_rub = price_rub + nkd
                
                print(f"  {bond.ticker}: цена={price_rub:.2f}₽ nkd={nkd:.2f} -> лот={lot_price_rub:.2f} ₽")
                
                bonds.append({
                    "figi": pos.figi,
                    "instrument_uid": pos.instrument_uid,
                    "ticker": bond.ticker,
                    "name": bond.name,
                    "quantity": quotation_to_float(pos.quantity),
                    "nominal": quotation_to_float(bond.nominal),
                    "nkd": nkd,
                    "lot_price_rub": lot_price_rub,
                    "current_price": price_rub,
                })
        return bonds
    except RequestError as e:
        print(f"Ошибка получения портфеля: {e}")
        return []
    except RequestError as e:
        print(f"Ошибка получения портфеля: {e}")
        return []
    except RequestError as e:
        print(f"Ошибка получения портфеля: {e}")
        return []
    except RequestError as e:
        print(f"Ошибка получения портфеля: {e}")
        return []

def get_bond_details(client, figi: str):
    try:
        bond = client.instruments.bond_by(
            id_type=InstrumentIdType.INSTRUMENT_ID_TYPE_FIGI,
            id=figi
        ).instrument
        
        coupon_value = 0.0
        try:
            from datetime import datetime, timedelta
            to_date = datetime.now()
            from_date = to_date - timedelta(days=365)
            
            coupons_response = client.instruments.get_bond_coupons(
                instrument_id=figi,
                from_=from_date,
                to=to_date
            )
            if coupons_response.events:
                coupon_value = quotation_to_float(coupons_response.events[0].pay_one_bond)
        except Exception as e:
            print(f"Не удалось получить купоны для {figi}: {e}")
        
        return {
            "figi": bond.figi,
            "ticker": bond.ticker,
            "name": bond.name,
            "nominal": quotation_to_float(bond.nominal),
            "coupon_quantity_per_year": bond.coupon_quantity_per_year,
            "coupon_value": coupon_value,
            "aci_value": quotation_to_float(bond.aci_value) if bond.aci_value else 0.0,
            "maturity_date": bond.maturity_date,
        }
    except RequestError as e:
        print(f"Ошибка получения данных облигации {figi}: {e}")
        return None

def calculate_coupon_per_period(bond_info) -> float:
    return bond_info.get("coupon_value", 0.0)
    nominal = bond_info.get("nominal", 0.0)
    # Ставка купона в процентах от номинала (например, 11.5)
    coupon_rate = bond_info.get("coupon_rate", 0.0)
    if coupon_rate <= 0:
        return 0.0
    return (coupon_rate / 100.0) * nominal / coupons_per_year

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
    lot_price_rub = bond["lot_price_rub"]
    if lot_price_rub <= 0:
        return 0
    quantity = int(free_rub // lot_price_rub)
    print(f"Цена лота (с НКД): {lot_price_rub:.2f} руб. Доступно: {free_rub:.2f} руб. Можно купить: {quantity} лотов")
    return quantity

def process_account(token: str, token_name: str):
    if not token:
        print("Ошибка: токен " + token_name + " не найден. Пропускаем.")
        return

    try:
        with Client(token) as client:
            accounts = client.users.get_accounts().accounts
            if not accounts:
                print("Нет доступных счетов для " + token_name)
                return
            account_id = accounts[0].id
            print("Используем счёт: " + account_id)

            free_rub = get_free_rub(client, account_id)
            print(f"Свободных рублей: {free_rub:.2f}")

            bonds = get_bonds_in_portfolio(client, account_id)

            if not bonds:
                print("В портфеле нет подходящих ОФЗ.")
            else:
                print(f"Найдено ОФЗ в портфеле: {len(bonds)}")
                for b in bonds:
                    print(f"  {b['ticker']}: цена={b['current_price']:.2f}₽, НКД={b['nkd']:.2f}₽, лот={b['lot_price_rub']:.2f}₽")

            print("--- Проверка условий для покупки ---")

            if free_rub < MIN_THRESHOLD_RUB:
                print(f"Сумма меньше порога {MIN_THRESHOLD_RUB} руб. Завершаем для {token_name}.")
                return

            if not bonds:
                return

            selected = select_bond_to_buy(client, bonds)
            if not selected:
                print("Нет подходящих ОФЗ для покупки (все отфильтрованы по НКД).")
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
        print(f"Ошибка API для {token_name}: {e}")


def main():
    token_1 = os.environ.get("TINKOFF_TOKEN")
    token_2 = os.environ.get("TINKOFF_TOKEN_2")

    if not token_1 and not token_2:
        print("Ошибка: ни один TINKOFF_TOKEN не найден")
        sys.exit(1)

    print("=" * 50)
    print("=== НАЧАЛО РАБОТЫ ПОМОЩНИКА ===")
    print("=" * 50)

    process_account(token_1, "Портфель 1")

    if token_2:
        process_account(token_2, "Портфель 2")
    else:
        print("Токен для Портфеля 2 не задан. Работаем только с одним.")


if __name__ == "__main__":
    main()
