# AG-UI Module Directory

This directory contains all AG-UI (Agent User Interaction Protocol) integration components for the WAFR project.

## Files Overview

### Core Components

- **`__init__.py`** - Package initialization and exports
- **`core.py`** - Official AG-UI SDK wrapper and WAFR-specific adapters
  - Wraps `ag-ui-protocol` SDK types (RunAgentInput, Message, Context, Tool, State)
  - Provides WAFR adapters (WAFRRunAgentInput, WAFRMessage, WAFRContext, WAFRTool)
  - Defines WAFR agent tools registry (8 agents)

### Event System

- **`events.py`** - Custom event definitions for WAFR/HITL workflow
  - HITL event types (review_required, synthesis_progress, etc.)
  - Event data classes (ReviewQueueSummary, SynthesisProgress, etc.)
  - Event factory functions

- **`emitter.py`** - AG-UI compliant event emitter
  - All 16 standard AG-UI event types
  - Custom HITL events
  - SSE-compatible streaming
  - Async event queue with heartbeat support

### State Management

- **`state.py`** - Complete state management for WAFR sessions
  - WAFRState class with nested components
  - JSON Patch deltas for incremental updates
  - State snapshots for initial sync
  - Session, Pipeline, Content, Review, Scores, Report state

### Integration

- **`orchestrator_integration.py`** - Orchestrator wrapper with AG-UI events
  - AGUIOrchestratorWrapper class
  - Tool call events for each agent
  - Message streaming for agent responses
  - Step-by-step event emission

- **`server.py`** - FastAPI SSE server
  - REST endpoints for WAFR processing
  - SSE event streaming
  - WebSocket support (optional)
  - Review decision endpoints

## Usage

### Basic Import

```python
from ag_ui import (
    WAFREventEmitter,
    WAFRState,
    HITLEvents,
    create_agui_orchestrator,
)
```

### Quick Start

```python
# Create AG-UI enabled orchestrator
orchestrator = create_agui_orchestrator(thread_id="session-123")

# Process with AG-UI events
results = await orchestrator.process_transcript_with_agui(
    transcript=transcript_text,
    session_id="session-123",
)
```

### Event Emitter

```python
emitter = WAFREventEmitter(thread_id="session-123")

# Emit events
await emitter.run_started()
await emitter.step_started("understanding")
await emitter.text_message_content("msg-1", "Processing...")
await emitter.step_finished("understanding", {"count": 15})
await emitter.run_finished()

# Stream events
async for event_data in emitter.stream_events():
    print(event_data)  # SSE format
```

### State Management

```python
state = WAFRState(session_id="session-123")

# Update state
state.update_step("understanding")
state.set_insights_count(15)

# Get snapshot
snapshot = state.to_snapshot()

# Get delta
delta = state.create_delta("/content/insights_count", 15)
```

## Module Structure

```
ag_ui/
├── __init__.py              # Package exports
├── core.py                  # Official SDK wrapper
├── events.py                # Custom HITL events
├── emitter.py               # Event emitter
├── state.py                 # State management
├── orchestrator_integration.py  # Orchestrator wrapper
├── server.py                # FastAPI server
└── README.md               # This file
```

## Dependencies

- `ag-ui-protocol>=0.1.0` - Official AG-UI SDK
- `fastapi>=0.100.0` - Web framework
- `sse-starlette>=1.6.0` - SSE support
- `websockets>=11.0.0` - WebSocket support

## Documentation

For comprehensive documentation, see:
- `AG_UI_INTEGRATION_GUIDE.md` - Complete integration guide
- `AG_UI_IMPLEMENTATION_SUMMARY.md` - Implementation summary
- Official AG-UI docs: https://docs.ag-ui.com

## Testing

```bash
# Run AG-UI tests
pytest tests/test_ag_ui.py -v

# Run with AG-UI integration
python run_wafr_with_agui.py --transcript transcript.txt
```

## Version

Current version: **1.0.0**

