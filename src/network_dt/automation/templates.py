"""Cisco IOS configuration templates and command generators.

Provides conceptual representations of Cisco IOS CLI commands deployed during
network automation, strictly conforming to the report specification.
"""

from typing import List, Optional


def render_ssh_commands(
    domain_name: str = "lab.local",
    rsa_key_size: int = 1024,
    username: str = "admin",
    password: str = "password123",
) -> List[str]:
    """Generate Cisco IOS commands to activate SSH v2 and administrative user.
    
    Reference: Section 2.1, Figure 5 of Rapport_TP_Reseau.pdf.
    """
    return [
        f"ip domain-name {domain_name}",
        f"crypto key generate rsa modulus {rsa_key_size}",
        "ip ssh version 2",
        f"username {username} privilege 15 secret {password}",
        "line vty 0 4",
        " login local",
        " transport input ssh",
        " exit",
    ]


def render_snmp_commands(
    community: str = "public",
    mode: str = "RO",
    location: str = "Lab",
    contact: str = "Admin",
) -> List[str]:
    """Generate Cisco IOS commands to activate SNMP server.
    
    Reference: Section 3.1, Figure 9 of Rapport_TP_Reseau.pdf.
    """
    return [
        f"snmp-server community {community} {mode}",
        f"snmp-server location {location}",
        f"snmp-server contact {contact}",
    ]


def render_vlan_commands(vlan_id: int, vlan_name: str) -> List[str]:
    """Generate Cisco IOS commands to define a VLAN on a Catalyst switch.
    
    Reference: Section 2.3 of Rapport_TP_Reseau.pdf.
    """
    return [
        f"vlan {vlan_id}",
        f" name {vlan_name}",
        " exit",
    ]


def render_access_port_commands(port_name: str, vlan_id: int) -> List[str]:
    """Generate Cisco IOS commands to configure an access port.
    
    Reference: Section 2.3 of Rapport_TP_Reseau.pdf.
    """
    return [
        f"interface {port_name}",
        " switchport mode access",
        f" switchport access vlan {vlan_id}",
        " no shutdown",
        " exit",
    ]


def render_trunk_port_commands(port_name: str, allowed_vlans: List[int]) -> List[str]:
    """Generate Cisco IOS commands to configure an 802.1Q trunk port.
    
    Reference: Section 2.3 of Rapport_TP_Reseau.pdf.
    """
    vlans_str = ",".join(str(v) for v in sorted(allowed_vlans))
    return [
        f"interface {port_name}",
        " switchport trunk encapsulation dot1q",
        " switchport mode trunk",
        f" switchport trunk allowed vlan {vlans_str}",
        " no shutdown",
        " exit",
    ]


def render_subinterface_commands(
    subif_name: str,
    dot1q_vlan: int,
    ip_address: str,
    netmask: str = "255.255.255.0",
) -> List[str]:
    """Generate Cisco IOS commands to configure an 802.1Q router subinterface.
    
    Reference: Section 2.3 of Rapport_TP_Reseau.pdf.
    """
    return [
        f"interface {subif_name}",
        f" encapsulation dot1Q {dot1q_vlan}",
        f" ip address {ip_address} {netmask}",
        " no shutdown",
        " exit",
    ]


def render_dhcp_pool_commands(
    pool_name: str,
    network: str,
    netmask: str,
    default_router: str,
    dns_server: str = "8.8.8.8",
    excluded_addresses: Optional[List[str]] = None,
) -> List[str]:
    """Generate Cisco IOS commands to configure a DHCP pool with exclusions.
    
    Reference: Section 2.4, Figure 7 of Rapport_TP_Reseau.pdf.
    """
    commands: List[str] = []
    if excluded_addresses:
        if len(excluded_addresses) == 2:
            commands.append(f"ip dhcp excluded-address {excluded_addresses[0]} {excluded_addresses[1]}")
        else:
            for addr in excluded_addresses:
                commands.append(f"ip dhcp excluded-address {addr}")

    commands.extend([
        f"ip dhcp pool {pool_name}",
        f" network {network} {netmask}",
        f" default-router {default_router}",
        f" dns-server {dns_server}",
        " exit",
    ])
    return commands
