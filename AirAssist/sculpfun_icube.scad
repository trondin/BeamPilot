use <threads.scad>
$fn = 96;

//fast_test = true;
fast_test = false;

// Main parameters
length = 86;
ext_dia = 34;
inn_dia = 32;
fins = 8;
fin_thickness = 1;
fin_dist = 3;
fin_width = 40;
bug_gap = 0.1; // Correction for OpenSCAD rendering
body_wall = 1;
body_height = length - 19;
core_diam = 20;
cavity_diam = 8;
vent_qty = 8;
vent_dia = 10;
ring_outer_diam = 16;
ring_inner_diam = 11;
ring_groove_depth = 1.6;
gap = 0.05;
tube_height = 19 + 4;

full();

// Main laser head assembly
module full()
{
  translate([0, 0, -36]) rotate([0, 180, 0])
  {
    holder(); 
    rotate([0, 0, 90]) translate([0, -28, 1]) rotate([0, 180, 0]) push_connector(); // Connector
    color("red") translate([0, 0, -6]) cylinder(h=45, d=1); // Laser beam
    color("LightGrey") translate([0, 0, 28]) nozzle(); // Nozzle
  }
}

// Module for BSPT R1/8" tapered thread
module bspt_thread(length = 7, internal = false)
{
  metric_thread(
    //diameter = 9.728, // Nominal diameter for R1/8"
    diameter = 9.728+0.17, // Adjusted nominal diameter for R1/8"
    pitch = 0.907,    // Thread pitch (28 threads per inch)
    length = length,
    internal = internal,
    n_starts = 1,     // Single thread
    thread_size = -1, // Default thread pitch
    groove = false,   // External thread (not cut)
    square = false,   // Standard V-shaped thread
    rectangle = 0,    // No rectangular profile
    angle = 30,       // Thread profile angle (60° for BSPT)
    taper = 1/16,     // Tapered thread
    leadin = 2,       // Chamfer at ends
    leadfac = 1.0,    // Chamfer scale
    test = fast_test  // Thread rendering enabled
  );
}

// Nozzle module
module nozzle()
{
  difference()
  {
    group()
    {
      // Main hexagonal cylinder of nozzle
      cylinder(h=3, d=8, $fn=6, center=true);
      // Conical transition
      translate([0, 0, (3+2)/2]) cylinder(h=2, d1=4, d2=2, center=true);
      // Lower part of nozzle
      translate([0, 0, -(3+8)/2]) cylinder(h=8, d=6, center=true);
    }
    // Central hole
    cylinder(h=40, d=1, center=true);
  }
}

// Connector module
module push_connector()
{
  difference()
  {
    group()
    {
      // BSPT R1/8" tapered thread
      rotate([180, 0, 0]) bspt_thread(length=7, internal=false);
      // Hexagonal part
      translate([0, 0, 7.6/2]) cylinder(h=7.6, d=13.5, center=true, $fn=6);
      // Spherical part
      translate([0, 0, 7.6]) scale([1, 1, 0.6]) sphere(d=11.6);
      // Transition cylinder
      translate([0, 0, 10.7]) cylinder(h=1, d=11, center=true);
      // Upper part of connector
      color("blue") translate([0, 0, 12]) cylinder(h=4, d=7.5, center=true);
      // Flat disc
      color("blue") translate([0, 0, 14]) resize(newsize=[12, 14, 2]) cylinder(h=1, d=1, center=true);
    }
    // Internal hole
    cylinder(h=40, d=6, center=true);
  }
}

// Side connector form module
module side_connector_form(diam=8)
{
  hull()
  {
    translate([0, 2, 0]) cylinder(d=diam, h=1, center=true);
    translate([0, -2, 0]) cylinder(d=diam, h=1, center=true);
    translate([0, 3, 34]) sphere(d=diam);
    translate([0, -3, 34]) sphere(d=diam);
  }    
}

// Side connector module
module side_connector()
{
  difference()
  {
    union()
    {
      // Connector body
      side_connector_form(8);
      // Cylindrical part
      translate([4, 0, 28]) rotate([0, 90, 0]) cylinder(d=14, h=8, center=true);
    }   
    // BSPT R1/8" internal thread
    translate([8 + bug_gap, 0, 28]) rotate([0, 90, 180]) bspt_thread(length=7, internal=true);  
  }
} 

// Holder module
module holder()
{
  base_length = 37;
  base_height = 2;
  base_radius = 1;
  base_hole = 31.5;
  hole_dia = 3.6;
  
  difference()  
  {  
    union()
    {
      difference()
      {
        // Base
        hull()
        {
          for (x = [-1, 1], y = [-1, 1]) 
          {
            translate([x * (base_length - 2) / 2, y * (base_length - 2) / 2, 0])
              cylinder(h = base_height, r = base_radius, center = true);
          }
        } 
        cube([base_length-6, base_length-6, 10], center=true);
      }      
      // Add side connector
      rotate([0, 0, 90]) translate([0, 0, 10]) rotate([90, 90, 0]) side_connector();
      for (x = [-1, 1], y = [-1, 1]) 
      {
        translate([x * (base_hole - 2) / 2, y * (base_hole - 2) / 2, 0])
          cylinder(h = 2, d = 8, center = true);
      }   
      cylinder(h = 2, d = 22, center = true);
      translate([0,0,7]) cylinder(h = 26, d = 17.4, center = true);
      //translate([10,0,-3.5]) cylinder(h = 5, d = 5, center = true);
      translate([0, base_length/4,0]) cube([4, base_length/2,2], center=true);
      translate([0, 0, -1]) rotate([0,0,120]) cube([3, base_length/2+1,2]);      
      translate([0, 0, -1]) rotate([0,0,-120]) cube([4.8, base_length/2+2,2]); 
      translate([8, -13, 0]) cube([7.5,9,2], center=true);       
      translate([0, 0, 23]) cylinder(h = 6, d1 = 17.5, d2=11, center = true);  
    }  
    
    for (x = [-1, 1], y = [-1, 1]) 
    {
      translate([x * (base_hole - 2) / 2, y * (base_hole - 2) / 2, 0])
       cylinder(h = 10, d = hole_dia, center = true);
    }    
    // O-ring groove
    translate([0, 0, -5.2]) difference()
    {
      cylinder(d=ring_outer_diam, h=ring_groove_depth + bug_gap, center=true);
      cylinder(d=ring_inner_diam, h=ring_groove_depth + bug_gap, center=true);
    }  

    translate([((base_length-3)/2-8),-16, 0]) cube([3.5, 7.1,20],center = true);       
    cylinder(h = 100, d = 9, center = true);    
    // Internal hole for side connector
    rotate([0, 0, 90]) translate([0, 0, 9.5]) rotate([90, 90, 0]) side_connector_form(5);
  }
  
  // Upper thread
  translate([0, 0, 23.5]) difference()
  {
    cylinder(d=11, h=6, center=true);
    translate([0, 0, -3.5]) metric_thread(diameter=6+0.15, pitch=1, length=7, internal=true, leadfac=1.0, test=fast_test);
  } 
  
  // Print support
  translate([29,0,20]) cube([10,0.5,13], center=true);
  translate([29,0,26.25]) cube([10,4,0.5], center=true);  
}

// Tube module
module holder2()
{
  difference()
  {
    union()
    {
      // Main tube ring
      difference()
      {
        union()
        {
          cylinder(d=inn_dia - gap, h=tube_height, center=true);
          translate([0, 0, (tube_height-4)/2])
            cylinder(d=inn_dia + 4, h=4, center=true);
        }
        cylinder(d=inn_dia - body_wall*3 - gap * 2, h=tube_height + bug_gap, center=true);
      }
      // Add side connector
      rotate([0, 0, 90]) translate([0, 0, 11.5]) rotate([90, 90, 0])
        side_connector();
      // Central cylinder
      cylinder(d=core_diam, h=tube_height, center=true);
      // Ventilation holes
      intersection()
      {
        cylinder(d=inn_dia - gap, h=tube_height, center=true);
        for (i = [0 : vent_qty - 1])
        {
          rotate([0, 0, i * 360 / vent_qty])
            translate([vent_dia/2, core_diam/2, 0])
            difference()
            {
              cylinder(d=vent_dia + 2, h=tube_height, center=true);
              cylinder(d=vent_dia - 2, h=tube_height + bug_gap, center=true);
              translate([vent_dia/2 + 1, 0, 0])
                cube([vent_dia, vent_dia, tube_height + bug_gap], center=true);
            }
        }
      }
      // Upper tube part
      translate([0, 0, (tube_height + 10)/2])
      {
        translate([0, 0, -1]) cylinder(d1=core_diam, d2=11, h=8, center=true);
        intersection()
        {
          translate([0, 0, -2]) cylinder(d1=inn_dia - gap, d2=10, h=6, center=true);
          group()
          {
            translate([0, 0, -2]) difference()
            {
              cylinder(d=inn_dia - gap, h=6, center=true);
              cylinder(d=inn_dia - body_wall - gap * 2, h=6 + bug_gap, center=true);
            }
            for (i = [0 : vent_qty - 1])
            {
              rotate([0, 0, i * 360 / vent_qty])
                translate([vent_dia/2, core_diam/2, 0])
              difference()
              {
                cylinder(d=vent_dia + 2, h=10, center=true);
                cylinder(d=vent_dia - 2, h=10 + bug_gap, center=true);
                rotate([0, 0, -35])
                  translate([vent_dia/2 + 1, 0, 0])
                    cube([vent_dia, vent_dia + 4, 10 + bug_gap], center=true);
                }
            }
          }
        }
      }
    }
    // Central hole
    cylinder(h=3 * tube_height, d=cavity_diam, center=true);
    // O-ring groove
    translate([0, 0, (-tube_height + ring_groove_depth)/2]) difference()
    {
      cylinder(d=ring_outer_diam, h=ring_groove_depth + bug_gap, center=true);
      cylinder(d=ring_inner_diam, h=ring_groove_depth + bug_gap, center=true);
    }
    
    // Internal hole for side connector
    rotate([0, 0, 90]) translate([0, 0, 11.5]) rotate([90, 90, 0]) side_connector_form(5);
  }
  // Upper thread
  translate([0, 0, 17]) difference()
  {
    cylinder(d=11, h=6, center=true);
    translate([0, 0, -3.5]) metric_thread(diameter=6+0.15, pitch=1, length=7, internal=true, leadfac=1.0, test=fast_test);
  } 
}