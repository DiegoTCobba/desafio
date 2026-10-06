"""Persistencia de activos en OCI Object Storage (capa Always Free) con respaldo local.

Credenciales (en este orden):
1. Variables de entorno: OCI_USER_OCID, OCI_TENANCY_OCID, OCI_FINGERPRINT, OCI_REGION y
   OCI_KEY_FILE (ruta a la llave .pem)  — útil al desplegar en una VM de OCI.
2. Archivo ~/.oci/config con el perfil indicado (por defecto DEFAULT).
"""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path


class AlmacenOCI:
    tipo = "oci"

    def __init__(self, bucket: str, perfil: str = "DEFAULT", config_file: str | None = None,
                 compartment_id: str | None = None, crear_bucket: bool = False):
        self.bucket, self.namespace = bucket, None
        self.disponible, self.detalle = False, ""
        try:
            import oci
        except ImportError:
            self.detalle = "El SDK 'oci' no está instalado (pip install oci)."
            return
        try:
            config = self._config(oci, perfil, config_file)
            oci.config.validate_config(config)
            self._oci = oci
            self.client = oci.object_storage.ObjectStorageClient(config)
            self.namespace = self.client.get_namespace().data
            cid = compartment_id or os.getenv("OCI_COMPARTMENT_ID") or config.get("tenancy")
            self._asegurar_bucket(cid, crear_bucket)
            self.disponible = True
            self.detalle = f"Conectado · namespace {self.namespace} · {config.get('region')}"
        except Exception as e:  # noqa: BLE001
            self.detalle = f"{type(e).__name__}: {str(e)[:200]}"

    @staticmethod
    def _config(oci, perfil, config_file):
        claves = ("OCI_USER_OCID", "OCI_TENANCY_OCID", "OCI_FINGERPRINT", "OCI_REGION", "OCI_KEY_FILE")
        if all(os.getenv(k) for k in claves):
            return {"user": os.getenv("OCI_USER_OCID"), "tenancy": os.getenv("OCI_TENANCY_OCID"),
                    "fingerprint": os.getenv("OCI_FINGERPRINT"), "region": os.getenv("OCI_REGION"),
                    "key_file": os.path.expanduser(os.getenv("OCI_KEY_FILE"))}
        return oci.config.from_file(file_location=config_file or oci.config.DEFAULT_LOCATION, profile_name=perfil)

    def _asegurar_bucket(self, compartment_id, crear):
        try:
            self.client.get_bucket(self.namespace, self.bucket)
        except self._oci.exceptions.ServiceError as e:
            if e.status != 404:
                raise
            if not crear:
                raise RuntimeError(f"El bucket '{self.bucket}' no existe. Créalo en la consola o marca "
                                   "'Crear bucket si no existe'.") from e
            detalles = self._oci.object_storage.models.CreateBucketDetails(
                name=self.bucket, compartment_id=compartment_id,
                public_access_type="NoPublicAccess", storage_tier="Standard")
            self.client.create_bucket(self.namespace, detalles)

    def guardar(self, nombre: str, contenido: str | bytes, content_type: str = "application/json") -> dict:
        try:
            data = contenido.encode("utf-8") if isinstance(contenido, str) else contenido
            r = self.client.put_object(self.namespace, self.bucket, nombre, data, content_type=content_type)
            return {"objeto": nombre, "status": "guardado_con_exito", "etag": r.headers.get("etag")}
        except Exception as e:  # noqa: BLE001
            return {"objeto": nombre, "status": "error", "detalle": str(e)[:200]}

    def listar(self, prefijo: str = "activos/") -> list[dict]:
        r = self.client.list_objects(self.namespace, self.bucket, prefix=prefijo, fields="name,size,timeCreated")
        return [{"objeto": o.name, "tamano_bytes": o.size,
                 "creado": o.time_created.strftime("%Y-%m-%d %H:%M") if o.time_created else ""}
                for o in r.data.objects]

    def leer(self, nombre: str) -> str:
        return self.client.get_object(self.namespace, self.bucket, nombre).data.content.decode("utf-8")


class AlmacenLocal:
    """Respaldo con la misma interfaz, para desarrollar sin credenciales de OCI."""
    tipo = "local"

    def __init__(self, bucket: str, base: str | Path = "salida_local"):
        self.bucket = bucket
        self.raiz = Path(base) / bucket
        self.raiz.mkdir(parents=True, exist_ok=True)
        self.disponible = True
        self.detalle = f"Respaldo local en {self.raiz}"

    def guardar(self, nombre, contenido, content_type="application/json"):
        destino = self.raiz / nombre
        destino.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(contenido, str):
            destino.write_text(contenido, encoding="utf-8")
        else:
            destino.write_bytes(contenido)
        return {"objeto": nombre, "status": "guardado_con_exito", "ruta_local": str(destino)}

    def listar(self, prefijo="activos/"):
        base = self.raiz / prefijo
        if not base.exists():
            return []
        return [{"objeto": str(p.relative_to(self.raiz)).replace("\\", "/"), "tamano_bytes": p.stat().st_size,
                 "creado": datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d %H:%M")}
                for p in sorted(base.rglob("*")) if p.is_file()]

    def leer(self, nombre):
        return (self.raiz / nombre).read_text(encoding="utf-8")
