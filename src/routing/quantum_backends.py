"""VLQ provider adapter used by the v9 physical-QPU experiment runner."""

import os
from abc import ABC, abstractmethod
from typing import Dict, Optional


class QuantumBackend(ABC):
    """Abstract quantum backend interface."""

    @abstractmethod
    def execute_circuit(self, circuit, shots: int = 1024) -> Dict:
        """Execute a quantum circuit and return measurement counts."""
        pass

    @abstractmethod
    def get_backend_info(self) -> Dict:
        """Return backend configuration info."""
        pass


class VLQBackend(QuantumBackend):
    """IT4Innovations VLQ (Ostrava) backend via LEXIS QaaS.

    The VLQ is a 24-qubit IQM superconducting QPU hosted at the
    IT4Innovations National Supercomputing Center under EuroHPC JU.
    It is accessed through the LEXIS platform using the ``py4lexis``
    and ``qaas`` Python packages.

    Credentials are read **exclusively from environment variables**::

        VLQ_PROJECT  – EuroHPC project ID  (e.g. OPEN-37-1)
        VLQ_RESOURCE – Queue/resource name  (e.g. VLQ-CZ)

    Never hard-code these values in source files committed to version
    control.  Store them in a local ``.env`` file (git-ignored) or
    export them in your shell session.

    Parameters
    ----------
    project : str, optional
        Overrides ``VLQ_PROJECT`` env var.  Use only in trusted,
        non-version-controlled scripts.
    resource : str, optional
        Overrides ``VLQ_RESOURCE`` env var.
    batch_size : int
        Maximum circuits to bundle into a single QaaS job submission.
        Larger batches reduce per-call overhead dramatically (default 100).
    """

    #: VLQ system specification (24-qubit IQM, star topology, 2600 CLOPS)
    SYSTEM_INFO: Dict = {
        "name": "VLQ",
        "provider": "IQM / IT4Innovations",
        "location": "Ostrava, CZ",
        "qubits": 24,
        "topology": "star",
        "clops": 2600,
        "single_qubit_gate_ns": 40,
        "two_qubit_gate_ns": 60,
        "access": "EuroHPC JU / LEXIS QaaS",
    }

    def __init__(
        self,
        project: Optional[str] = None,
        resource: Optional[str] = None,
        batch_size: int = 100,
    ) -> None:
        import os
        self._project: str = project or os.environ.get("VLQ_PROJECT", "")
        self._resource: str = resource or os.environ.get("VLQ_RESOURCE", "")
        self.batch_size: int = batch_size
        self._backend = None   # qaas.QBackend, populated lazily
        self._token: Optional[str] = None

        if not self._project:
            raise ValueError(
                "VLQ project ID not configured. "
                "Export VLQ_PROJECT=<your-project-id> before running."
            )
        if not self._resource:
            raise ValueError(
                "VLQ resource not configured. "
                "Export VLQ_RESOURCE=<resource-id> (e.g. VLQ-CZ) before running."
            )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _authenticate(self) -> str:
        """Trigger LEXIS OAuth2 flow and return a fresh access token."""
        # Check for local gitignored token override
        token_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "lexis_token.txt")
        if os.path.exists(token_path):
            print(f"[VLQBackend] Found cached token at {token_path}, loading...")
            try:
                with open(token_path, "r") as tf:
                    token = tf.read().strip()
                if token:
                    return token
            except Exception as e:
                print(f"[VLQBackend] Warning: Failed to read token file: {e}")

        try:
            from py4lexis.session import LexisSession  # type: ignore[import-untyped]
        except ImportError as exc:
            raise ImportError(
                "py4lexis is not installed. "
                "Run: pip install --index-url "
                "https://opencode.it4i.eu/api/v4/projects/107/packages/pypi/simple py4lexis"
            ) from exc

        print("[VLQBackend] Opening LEXIS authentication page …")
        session = LexisSession()
        token = session.get_access_token()
        if not token:
            raise RuntimeError("LEXIS authentication failed: no token returned.")
        print("[VLQBackend] Token obtained successfully.")
        return token

    def _init(self) -> None:
        """Authenticate and bind to the VLQ QaaS backend."""
        try:
            from qaas.client import QProvider  # type: ignore[import-untyped]
        except ImportError as exc:
            raise ImportError(
                "qaas is not installed. Run: pip install qaas==0.4.2"
            ) from exc

        self._token = self._authenticate()
        # QaaS 0.4.x takes the project as the first argument and the OAuth
        # token by keyword.  The legacy positional order makes the JWT look
        # like a project identifier and fails before any VLQ job is created.
        provider = QProvider(self._project, token=self._token)
        self._backend = provider.get_backend(self._resource)
        print(
            f"[VLQBackend] Connected to resource '{self._resource}' "
            f"on project '{self._project}'."
        )

    # ------------------------------------------------------------------
    # QuantumBackend interface
    # ------------------------------------------------------------------

    def execute_circuit(self, circuit, shots: int = 1024) -> Dict:
        """Execute a single Qiskit circuit on the VLQ QPU.

        The circuit is transpiled with Qiskit's standard transpiler then
        submitted to the VLQ via QaaS.  Results are returned as a standard
        Qiskit counts dict (bitstring -> count).
        """
        if self._backend is None:
            self._init()
        from qiskit import transpile
        transpiled = transpile(circuit, self._backend)
        job = self._backend.run(transpiled, shots=shots)
        return job.result().get_counts()

    def execute_batch(self, circuits: list, shots: int = 1024) -> list:
        """Submit a list of circuits in batches to minimise QaaS overhead.

        Circuits are dynamically packed (multi-programming) into the QPU's width
        to maximize throughput (v9 uses 13 qubits and therefore runs one circuit per packing slot).
        
        Returns
        -------
        list[dict]
            One counts dict per input circuit, in original order.
        """
        if self._backend is None:
            self._init()

        from qiskit import transpile, QuantumCircuit

        qubits_per_circuit = circuits[0].num_qubits
        clbits_per_circuit = circuits[0].num_clbits
        pack_size = 24 // qubits_per_circuit if qubits_per_circuit > 0 else 1
        pack_size = max(1, pack_size)
        
        packed_circuits = []
        pack_lengths = []
        
        for i in range(0, len(circuits), pack_size):
            chunk = circuits[i : i + pack_size]
            pack_lengths.append(len(chunk))
            if len(chunk) == 1:
                packed_circuits.append(chunk[0])
            else:
                packed_qc = QuantumCircuit(len(chunk) * qubits_per_circuit, len(chunk) * clbits_per_circuit)
                for j, qc in enumerate(chunk):
                    q_offset = j * qubits_per_circuit
                    c_offset = j * clbits_per_circuit
                    packed_qc.compose(
                        qc,
                        qubits=list(range(q_offset, q_offset + qubits_per_circuit)),
                        clbits=list(range(c_offset, c_offset + clbits_per_circuit)),
                        inplace=True
                    )
                packed_circuits.append(packed_qc)

        all_counts: list = []
        total = len(packed_circuits)
        
        for start in range(0, total, self.batch_size):
            chunk = packed_circuits[start : start + self.batch_size]
            chunk_lengths = pack_lengths[start : start + self.batch_size]
            
            transpiled_chunk = [transpile(c, self._backend) for c in chunk]
            n_batch = start // self.batch_size + 1
            n_total = (total - 1) // self.batch_size + 1
            print(
                f"[VLQBackend] Submitting batch {n_batch}/{n_total} "
                f"({len(chunk)} packed circuits, containing {sum(chunk_lengths)} original circuits) …"
            )
            job = self._backend.run(transpiled_chunk, shots=shots)
            result = job.result()
            for i, p_len in enumerate(chunk_lengths):
                try:
                    packed_counts = result.get_counts(i)
                except Exception:
                    packed_counts = result.get_counts()
                    
                if p_len == 1:
                    all_counts.append(packed_counts)
                else:
                    unpacked_dicts = [{} for _ in range(p_len)]
                    for bitstring, count in packed_counts.items():
                        clean_bits = bitstring.replace(" ", "")
                        for j in range(p_len):
                            end_idx = len(clean_bits) - j * clbits_per_circuit
                            start_idx = len(clean_bits) - (j + 1) * clbits_per_circuit
                            c_bits = clean_bits[start_idx:end_idx]
                            unpacked_dicts[j][c_bits] = unpacked_dicts[j].get(c_bits, 0) + count
                            
                    all_counts.extend(unpacked_dicts)

        return all_counts

    def get_backend_info(self) -> Dict:
        return {
            **self.SYSTEM_INFO,
            "type": "quantum_hpc",
            "batch_size": self.batch_size,
            "project": self._project,
            "resource": self._resource,
        }
