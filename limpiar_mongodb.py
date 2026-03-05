"""
SCRIPT DE LIMPIEZA DE MONGODB
Ejecutar UNA VEZ antes de reiniciar el servidor.

Elimina todos los trades generados por auditoria automatica.
Estos son trades FALSOS que corrompieron las estadisticas.

Uso:
    cd C:\\Users\\muste\\Pocket-option-bot
    python limpiar_mongodb.py
"""

import asyncio
from motor.motor_asyncio import AsyncIOMotorClient

MONGO_URL = "mongodb://localhost:27017"
DB_NAME   = "trading_bot"

async def main():
    print("=" * 60)
    print("LIMPIEZA DE TRADES FALSOS EN MONGODB")
    print("=" * 60)
    print()

    client = AsyncIOMotorClient(MONGO_URL)
    db     = client[DB_NAME]

    total_antes  = await db.trades.count_documents({})
    falsos       = await db.trades.count_documents(
        {"source": {"$in": ["auto_audit", "auto_audit_verified"]}}
    )
    pendientes   = await db.trades.count_documents(
        {"source": {"$exists": False}, "result": {"$in": [None, "", "pending"]}}
    )
    reales       = await db.trades.count_documents(
        {"result": {"$in": ["win", "loss"]},
         "source": {"$nin": ["auto_audit", "auto_audit_verified"]}}
    )

    print("Estado actual de MongoDB:")
    print("  Total trades:          " + str(total_antes))
    print("  Trades FALSOS:         " + str(falsos))
    print("  Sin resultado:         " + str(pendientes))
    print("  Trades REALES:         " + str(reales))
    print()

    if falsos == 0 and pendientes == 0:
        print("No hay trades falsos. MongoDB ya esta limpio.")
        client.close()
        return

    print("Se eliminaran " + str(falsos + pendientes) + " trades falsos.")
    print("Los " + str(reales) + " trades reales se conservaran.")
    print()
    resp = input("Continuar? (escribe si para confirmar): ").strip().lower()

    if resp != "si":
        print("Operacion cancelada.")
        client.close()
        return

    r1 = await db.trades.delete_many(
        {"source": {"$in": ["auto_audit", "auto_audit_verified"]}}
    )
    r2 = await db.trades.delete_many(
        {"source": {"$exists": False}, "result": {"$in": [None, "", "pending"]}}
    )

    eliminados = r1.deleted_count + r2.deleted_count
    restantes  = await db.trades.count_documents({})

    print()
    print("Limpieza completada:")
    print("  Eliminados:  " + str(eliminados) + " trades falsos")
    print("  Conservados: " + str(restantes) + " trades reales")
    print()
    print("Ahora puedes reiniciar el backend con el server.py nuevo.")
    client.close()

if __name__ == "__main__":
    asyncio.run(main())
