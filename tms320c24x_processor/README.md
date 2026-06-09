# TMS320C24x Processor Module for Ghidra

This module provides P-code definitions and processor support for the Texas Instruments TMS320C24x family of 16-bit fixed-point digital signal processors (DSPs).

## Supported Processors

- TMS320C240 - Motor control DSP with PWM, ADC, and CAN
- TMS320C241 - Enhanced motor control DSP
- TMS320C242 - General purpose DSP with enhanced peripherals
- TMS320C243 - Enhanced general purpose DSP
- TMS320C244 - Advanced motor control DSP

## Features

### Instruction Set Support
- Complete TMS320C24x instruction set including:
  - Arithmetic operations (ADD, SUB, MPY, etc.)
  - Logic operations (AND, OR, XOR, etc.)
  - Data movement (LAC, SAC, BLDD, etc.)
  - Branch and call instructions (B, CALL, RET, etc.)
  - Bit manipulation (BIT, BITT, etc.)
  - Accumulator operations (ABS, NEG, SFL, SFR, etc.)
  - Auxiliary register operations (LAR, SAR, MAR, etc.)
  - Repeat instructions (RPT, RPTK)
  - I/O operations (IN, OUT)

### Register Model
- ACC/ACCB - Primary/secondary accumulators
- PREG - Product register for multiply operations
- TREG0-TREG2 - Temporary registers
- AR0-AR7 - Auxiliary registers for addressing
- Status registers (ST0, ST1) with individual bit tracking
- Data page pointer (DP) for memory banking
- Stack pointer (SP) and program counter (PC)

### Memory Spaces
- **PROG** - Program memory space (Harvard architecture)
- **DATA** - Data memory space with page addressing
- **IO** - I/O memory mapped registers
- **RAM** - Internal RAM areas

### Addressing Modes
- Direct addressing with data page support
- Indirect addressing via auxiliary registers
- Immediate addressing for constants
- Memory-mapped I/O addressing

## Installation

1. Copy the entire `tms320c24x_processor` directory to your Ghidra installation:
   ```
   <GHIDRA_INSTALL>/Ghidra/Processors/TMS320C24x/
   ```

2. Alternatively, for user-specific installation:
   ```
   <USER_HOME>/.ghidra/.ghidra_<version>/Extensions/TMS320C24x/
   ```

3. Restart Ghidra for the processor module to be recognized.

## Usage

### Loading Firmware
1. Open Ghidra and create a new project
2. Import your TMS320C24x binary file
3. In the import dialog, select "TMS320C24x" as the processor
4. Choose the appropriate variant (C240, C241, etc.)
5. Set the base address for your firmware (typically 0x0000 for boot code)

### Supported File Formats
- Raw binary files (`.bin`, `.c24x`, `.c240`, etc.)
- Intel HEX format (`.hex`)
- Motorola S-Record format (`.s19`, `.s28`, `.s37`, `.srec`)
- TI COFF object files (`.out`, `.cof`)
- ELF files with TI machine types

### Memory Layout Configuration
The processor spec includes common memory layouts:
- **Data Page 0**: 0x0000-0x007F (CPU registers and immediate data)
- **Data RAM**: 0x0200-0x04FF (user data memory)
- **Program RAM**: 0x0000-0x7FFF (program code)
- **I/O Space**: 0x0000-0xFFFF (memory-mapped peripherals)

### Interrupt Vectors
The module defines standard TMS320C24x interrupt vectors:
- RESET (0x0000)
- INT1-INT6 (0x0002-0x000C)
- TINT, RINT, XINT (0x000E-0x0012)
- TRAP, NMI (0x0014-0x0016)
- User interrupts (0x0018-0x001E)

### Peripheral Registers
Common peripheral registers are pre-defined:
- **Timer registers**: T1CON, T1CNT, T1CMPR, T1PR, etc.
- **SCI registers**: SCICCR, SCICTL1, SCIRXBUF, SCITXBUF, etc.
- **SPI registers**: SPICCR, SPICTL, SPIRXBUF, SPITXBUF, etc.
- **ADC registers**: ADCTRL1-3, ADCFIFO1-4, etc.
- **PWM registers**: GPTCONA, T3CON-T4PR, etc.

## Decompilation

The module includes calling convention definitions for proper C decompilation:
- Function parameters passed via ACC/ACCB and stack
- Return values in ACC
- Preserved registers: SP, AR0-AR7, DP
- Volatile registers: ACC, ACCB, PREG, TREG0-TREG2

## Limitations

This is a basic implementation with the following limitations:
- Some advanced addressing modes may need refinement
- Peripheral-specific behaviors are simplified
- Timing and cycle-accurate simulation not implemented
- Some variant-specific instructions may be missing

## Contributing

To extend or improve this module:
1. Edit the `.sleigh` file for instruction semantics
2. Update `.pspec` for processor-specific behaviors
3. Modify `.cspec` for calling convention changes
4. Adjust `.ldefs` for new processor variants

## References

- TMS320C24x DSP Controller Reference Set, Texas Instruments
- TMS320C24x DSP Controllers CPU and Instruction Set Reference Guide
- Ghidra Software Reverse Engineering Framework Documentation

## License

This processor module is provided as-is for educational and research purposes. Refer to your Ghidra license for usage terms.