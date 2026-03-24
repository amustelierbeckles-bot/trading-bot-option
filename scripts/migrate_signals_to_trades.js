/**
 * migrate_signals_to_trades.js
 * ─────────────────────────────────────────────────────────────────────────────
 * Migración UNA VEZ: mueve los trades auto-exec mal ubicados en db.signals
 * hacia db.trades, marcándolos con source="auto_exec" y migrated_from_signals=true.
 *
 * CÓMO EJECUTAR (en el servidor):
 *   mongosh "mongodb://localhost:27017/pocket_option_bot" scripts/migrate_signals_to_trades.js
 *
 * IDEMPOTENTE: usa insertOne con comprobación previa por _id —
 *   si se ejecuta dos veces, los documentos ya migrados no se duplican.
 * ─────────────────────────────────────────────────────────────────────────────
 */

// ── Configuración ────────────────────────────────────────────────────────────
// Identifica documentos de auto-exec dentro de db.signals por la presencia del
// campo "po_order_id" (añadido por auto_exec.py al ejecutar una orden en PO).
const SIGNAL_QUERY = {
  "po_order_id": { $exists: true },
};

// ── Estadísticas ─────────────────────────────────────────────────────────────
let migrated  = 0;
let skipped   = 0;  // ya existe en db.trades
let errored   = 0;

print("=== Iniciando migración db.signals → db.trades ===");
print(`Fecha: ${new Date().toISOString()}`);

const cursor = db.signals.find(SIGNAL_QUERY);

cursor.forEach(function (doc) {
  // Comprobación de idempotencia: si ya existe en db.trades, saltar.
  const exists = db.trades.findOne({ _id: doc._id });
  if (exists) {
    skipped++;
    return;
  }

  // Enriquecer el documento antes de insertar.
  doc.source                = "auto_exec";
  doc.migrated_from_signals = true;
  doc.migrated_at           = new Date();

  try {
    db.trades.insertOne(doc);
    db.signals.deleteOne({ _id: doc._id });
    migrated++;
  } catch (e) {
    print(`ERROR al migrar _id=${doc._id}: ${e.message}`);
    errored++;
  }
});

print("─────────────────────────────────────────────");
print(`✅ Migrados:  ${migrated}`);
print(`⏭  Ya existían en trades (saltados): ${skipped}`);
print(`❌ Errores:   ${errored}`);
print("=== Migración completada ===");
