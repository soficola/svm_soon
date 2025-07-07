# svm_soon: Cross-Chain Bridge Event Listener Simulation

This repository contains a Python-based simulation of an off-chain event listener and relayer, a critical component in many cross-chain bridge architectures. The script is designed to monitor a smart contract on a source blockchain (e.g., Ethereum), detect specific events (`TokensLocked`), and simulate the process of relaying this information to a destination chain.

## Concept

Cross-chain bridges allow users to transfer assets or data from one blockchain to another. A common pattern for this is the "lock-and-mint" mechanism:

1.  **Lock**: A user locks their assets in a smart contract on the source chain (e.g., Ethereum).
2.  **Event Emission**: The smart contract emits an event (e.g., `TokensLocked`) containing details of the deposit, such as the recipient's address on the destination chain and the amount.
3.  **Listen & Verify**: Off-chain services, often called "listeners" or "validators," monitor the source chain for these specific events.
4.  **Relay**: Upon detecting a valid event, the listener relays this information to the destination chain.
5.  **Mint**: A smart contract on the destination chain verifies the relayed information and mints a corresponding amount of a "wrapped" token for the recipient.

This script simulates the off-chain components described in steps 3 and 4. It provides a robust framework for listening to on-chain events and triggering corresponding off-chain actions.

## Code Architecture

The system is built with a modular, object-oriented design to separate concerns and enhance maintainability. The core components are:

*   **`BlockchainConnector`**: A wrapper around the `web3.py` library. Its sole responsibility is to manage the connection to a source chain's RPC node. It handles connection checks, retries, and provides a simple interface to fetch blockchain data.

*   **`EventScanner`**: This class uses a `BlockchainConnector` instance to scan a range of blocks for a specific event from a designated smart contract. It is designed to be state-agnostic, simply taking a block range and returning any events it finds.

*   **`CrossChainTransactionRelayer`**: This component's job is to take the event data found by the scanner, format it into a standardized payload, and simulate sending it to the destination chain. In this simulation, it makes an HTTP POST request to a mock API endpoint using the `requests` library.

*   **`BridgeOrchestrator`**: The main class that ties everything together. It manages the application's state (i.e., the last block number it has successfully scanned) and runs the main control loop. It coordinates the other components to create a continuous scanning and relaying process.

Here is a high-level diagram of the architecture:

```
[ BridgeOrchestrator ] (Main Loop & State)
         |
         | coordinates
         v
+-------------------------------------------------------------+
|        |                       |                            |
|        v                       v                            v
| [BlockchainConnector] <--> [EventScanner]         [CrossChainTransactionRelayer] |
|  (manages RPC conn)      (scans blocks for events)    (processes & sends events)   |
|        |                       ^                            |
|        v                       | uses                       v
| [Source Chain RPC]                                [Destination Chain Mock API] |
| (e.g., Infura/Alchemy)                            (e.g., a relayer service)    |
+-------------------------------------------------------------+
```

## How it Works

The script executes a continuous cycle:

1.  **Initialization**: The `BridgeOrchestrator` is instantiated. It initializes the `BlockchainConnector` to connect to the source chain RPC. It determines the starting block for scanning (either a specified block or the latest block minus a confirmation delay).

2.  **Main Loop**: The orchestrator enters an infinite loop.

3.  **Block Head Check**: In each cycle, it queries the `BlockchainConnector` for the latest block number on the source chain.

4.  **Determine Scan Range**: It calculates the range of blocks to scan, from `last_scanned_block + 1` up to `latest_block - CONFIRMATION_BLOCKS`. The confirmation delay is crucial to avoid acting on events from blocks that might be orphaned in a chain reorganization.

5.  **Scan in Chunks**: To avoid overwhelming public RPC nodes, the orchestrator divides the total scan range into smaller chunks (defined by `MAX_BLOCK_RANGE`). It instructs the `EventScanner` to process one chunk at a time.

6.  **Event Detection**: The `EventScanner` queries the RPC node for logs matching the `TokensLocked` event signature within the given block chunk.

7.  **Process and Relay**: If any events are found, they are passed one by one to the `CrossChainTransactionRelayer`.
    *   The relayer transforms the raw event data into a clean JSON payload.
    *   It sends this payload via an HTTP POST request to a simulated destination endpoint.

8.  **Update State**: After a chunk of blocks is successfully scanned, the `BridgeOrchestrator` updates its `last_scanned_block` state variable.

9.  **Wait**: Once the entire range up to the target block has been processed, the orchestrator pauses for a configured interval (`SCAN_INTERVAL_SECONDS`) before starting the cycle again.

## Usage Example

### 1. Prerequisites

*   Python 3.8+
*   An RPC URL for an Ethereum-compatible blockchain (e.g., from [Infura](https://infura.io/) or [Alchemy](https://www.alchemy.com/)). This example is configured for the Goerli testnet.

### 2. Setup

First, clone the repository:
```bash
git clone https://github.com/your-username/svm_soon.git
cd svm_soon
```

Create and activate a Python virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows, use `venv\Scripts\activate`
```

Install the required dependencies:
```bash
pip install -r requirements.txt
```

Create a `.env` file in the root directory of the project to store your RPC URL. This keeps your sensitive information out of the source code.

```
# .env file
SOURCE_CHAIN_RPC_URL="https://your-ethereum-rpc-url-here"
```

You can also override other configuration constants like `BRIDGE_CONTRACT_ADDRESS` in this file.

### 3. Running the Script

Execute the script from your terminal:

```bash
python script.py
```

The script will start, connect to the blockchain, and begin its scanning loop. You will see log output indicating its progress.

**Example Output:**

```
2023-10-27 10:30:00,123 - INFO - [script.connect] - Successfully connected to blockchain node at https://rpc.ankr.com/eth_goerli
2023-10-27 10:30:00,456 - INFO - [script.<module>] - Orchestrator initialized. Starting scan from block 9876540.
2023-10-27 10:30:00,457 - INFO - [script.run] - Starting bridge orchestrator main loop... (Press Ctrl+C to stop)
2023-10-27 10:30:01,890 - INFO - [script.scan_blocks] - Scanning for 'TokensLocked' events from block 9876541 to 9877040.
2023-10-27 10:30:05,112 - INFO - [script.scan_blocks] - Found 1 'TokensLocked' event(s) in block range.
2023-10-27 10:30:05,113 - INFO - [script.process_and_relay] - Prepared payload for transaction 0xabc123...
2023-10-27 10:30:05,550 - INFO - [script.process_and_relay] - Successfully relayed transaction. Destination response ID: 101
2023-10-27 10:30:05,999 - INFO - [script.run] - Cycle finished. Waiting 15 seconds for the next one.
```
