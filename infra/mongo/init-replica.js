const limite = Date.now() + 120000;
let admin;
while (Date.now() < limite) {
  try {
    const candidato = new Mongo("mongodb://mongodb:27017/?directConnection=true&serverSelectionTimeoutMS=2000").getDB("admin");
    const ping = candidato.runCommand({ping: 1});
    if (!ping.ok) throw new Error("ping rechazado");
    admin = candidato;
    break;
  } catch (error) {
    sleep(500);
  }
}
if (!admin) throw new Error("MongoDB no responde dentro de 120 segundos.");

let resultado;
try {
  resultado = admin.runCommand({replSetGetConfig: 1});
} catch (error) {
  if (error.code !== 94) throw error; 
  try {
    admin.runCommand({
      replSetInitiate: {_id: "rs0", members: [{_id: 0, host: "mongodb:27017"}]}
    });
  } catch (inicio) {
    if (inicio.code !== 23) throw inicio; 
  }
  resultado = admin.runCommand({replSetGetConfig: 1});
}
if (!resultado.ok) throw new Error("No se pudo leer replica set: " + resultado.codeName);
const config = resultado.config;
if (config._id !== "rs0" || config.members.length !== 1 || config.members[0].host !== "mongodb:27017") {
  throw new Error("Replica set existente incompatible; se conserva sin reconfigurarlo.");
}

while (Date.now() < limite) {
  const hello = admin.runCommand({hello: 1});
  if (hello.ok && hello.isWritablePrimary && hello.setName === "rs0") {
    print("rs0 listo: primario real confirmado; configuración existente conservada.");
    quit(0);
  }
  sleep(500);
}
throw new Error("rs0 no eligió un primario dentro del plazo.");
